
try:
    from urllib.request import urlopen, build_opener
    from urllib.parse import quote
except ImportError:
    from urllib2 import urlopen, quote, build_opener

from bs4 import BeautifulSoup

from irc import bot

# Set up logging.

import os
import logging
import logging.handlers
logger = logging.getLogger(__file__)

def setup_logging(filename, path=None, verbose=False):
    if not path:
        path = os.path.dirname(os.path.realpath(__file__))
    file_log = logging.handlers.TimedRotatingFileHandler(
        os.path.join(path, filename),
        when="midnight",
        backupCount=31)
    file_log.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_log.setFormatter(logging.Formatter('%(asctime)-15s (%(name)s) %(message)s'))
    logger.addHandler(file_log)

setup_logging("luser.log")

NAME = "luser"
luser = bot.SingleServerIRCBot([("chat.freenode.net", 8000)], NAME, NAME)

def change_nick(c, e):
    from random import randint
    c.nick('{}-{}'.format(c.get_nickname(), str(randint(0, 9))))
luser.on_nicknameinuse = change_nick

def join_channels(c, e):
    c.join("#{}-test".format(NAME))
    c.join("#vn"+NAME)
luser.on_welcome = join_channels

def handle(c, e, msg):
    try:
        if 'http' in msg:
            c.privmsg(e.target, title(msg))
        if msg[0] not in ('.', '!', ':'): return
        reply = ''
        if msg[1:3] == 'g ':
            reply = google(msg[3:])
        if msg[1:4] == 'wa ':
            reply = wolframalpha(msg[4:])
        if msg[1:4] == 'tr ':
            reply = translate(msg[4:])
        if reply:
            # Keep PRIVMSG under 512bytes
            c.privmsg(e.target, reply[:512 - len(e.target) - 50])
    except Exception as e:
        logger.error('%s causes: %s' % (msg, str(e)))

# List other <<botname>>s, and update that list when one joins or quits.
#    This list is used by the <<botname>>s to decide whether to handle
#    unaddressed messages. If the length of the IRC prefix
#    'nick!user@host' for a message indexes to its name, that <<botname>>
#    response.

lusers = []
def list_lusers(c, e):
    for luser in filter(lambda n: n.startswith(NAME), e.arguments[-1].split(' ')):
        if luser not in lusers:
            lusers.append(luser)
    if c.get_nickname() not in lusers:
        c.reconnect()
    lusers.sort()
luser.on_namreply = list_lusers

# The next lambdas are abusing python logical operator, but they read
#    like English.

def luser_joins(c, e):
    if e.source.nick not in lusers:
        lusers.append(e.source.nick)
        lusers.sort()
luser.on_join = lambda c, e: e.source.startswith(NAME) and luser_joins(c, e)

def luser_quits(c, e):
    lusers.remove(e.source.nick)
luser.on_quit = lambda c, e: e.source.startswith(NAME) and luser_quits(c, e)

# Actual message processing. Ignore the other <<botname>>s.

last_lines = {}
def on_pubmsg(c, e):
    nick = e.source.nick
    if nick.startswith(NAME): return
    my_nick = c.get_nickname()
    msg = e.arguments[0]
    addressed = msg.startswith(my_nick)
    def handling(e):
        return lusers[len(e.source) % len(lusers)] == my_nick
    if msg == "report!":
        return c.privmsg(e.target, "operated by hdhoang with source code " + post_source())
    if msg.startswith('s/'):
        parts = msg.split('/')
        if len(parts) >= 3 and handling(e) and nick in last_lines:
            return c.privmsg(e.target, "{} meant: {}".format(nick,
                                                        last_lines[nick]
                                                        .replace(parts[1], parts[2])))
    else:
        last_lines[nick] = msg
    if addressed or handling(e):
        if addressed:
            msg = msg[len(my_nick) +2:] # remove addressing
        handle(c, e, msg)
luser.on_pubmsg = on_pubmsg

def title(text):
    titles = []
    urls = filter(lambda w: w.startswith('http'), text.split())
    for u in urls:
        request = build_opener()
        request.addheaders = [('Accept-Encoding', 'gzip')]
        response = request.open(u)
        if response.info().get('Content-Encoding') == 'gzip':
            from gzip import GzipFile
            if '__loader__' in globals():
                response = GzipFile(fileobj=response)
            else:
                from StringIO import StringIO
                response = GzipFile(fileobj=StringIO(response.read()))
        title = BeautifulSoup(response.read(50000), 'html.parser').title
        response.close()
        if title: titles.append(title.string.replace('\n', '').strip())
    return ' / '.join(titles)

def wolframalpha(text):
    import xml.etree.ElementTree as ET
    with urlopen('http://api.wolframalpha.com/v2/query?format=plaintext&appid=3JEW42-4XXE264A93&input=' + quote(text)) as r:
        tree = ET.parse(r)
        reply = ''
        for n in tree.iter():
            if n.tag == 'pod':
                reply += n.attrib['title'] + ': '
            if n.tag == 'plaintext' and n.text and len(n.text.strip()):
                reply += n.text + ' / '
        if len(reply) > 512:
            reply = reply[:200] + " http://wolframalpha.com/?input=" + quote(text)
        return reply.replace('\n', ' ')

def google(text):
    import json
    with urlopen('https://ajax.googleapis.com/ajax/services/search/web?v=1.0&rsz=1&q=' + quote(text)) as r:
        data = json.loads(r.read().decode())['responseData']
        if not data['results']:
            return '0 result'
        return data['results'][0]['titleNoFormatting'] + ' ' + data['results'][0]['unescapedUrl']

def translate(text):
    import json
    (lang, _, text) = text.partition(' ')
    if not text:
        return 'Missing text'
    with urlopen('https://translate.yandex.net/api/v1.5/tr.json/translate?key=trnsl.1.1.20160210T093900Z.c6eacf09bbb65cfb.cc28de2ba798bc3bc118e9f8201b6e6cea697810&text={}&lang={}'.format(quote(text), lang)) as r:
        data = json.loads(r.read().decode())
        return data['lang'] + ": " + data['text'][0]

def post_source():
    try:
        from http.client import HTTPConnection
    except ImportError:
        from httplib import HTTPConnection
    conn = HTTPConnection('ix.io')
    conn.request('POST', '/', 'read:1=3&name:1=luser.py&f:1=' + quote(open(__file__).read()))
    return conn.getresponse().read().decode().strip()

luser.start()
