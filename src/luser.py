import sys
import logging
import logging.handlers
import os

reload(sys)
sys.setdefaultencoding('utf8')

try:
    from urllib.request import urlopen
    from urllib.parse import quote
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, quote, HTTPError

from bs4 import BeautifulSoup

from irc import bot
NAME = 'luser'
lusers = []
luser = bot.SingleServerIRCBot([("chat.freenode.net", 8000)], NAME, NAME)
logger = logging.getLogger(__name__)


def setup_logging(logfile, verbose, work_dir):
  log_path = os.path.join(work_dir, 'log')
  if not os.path.isdir(log_path):
    os.mkdir(log_path)

  formatter = logging.Formatter('%(asctime)-15s (%(name)s) %(message)s')
  log_level = logging.DEBUG if verbose else logging.INFO

  if logfile:
    logfile = os.path.join(log_path, logfile)
    file_log = logging.handlers.TimedRotatingFileHandler(
      logfile,
      when="midnight",
      backupCount=31)
    file_log.setLevel(log_level)
    file_log.setFormatter(formatter)
    logger.addHandler(file_log)

def change_nick(c, e):
    from random import randint
    c.nick('{}-{}'.format(c.get_nickname(), str(randint(0, 9))))
luser.on_nicknameinuse = change_nick

def join_channels(c, e):
    c.join("#{}-test".format(NAME))
    c.join("#vn"+NAME)
luser.on_welcome = join_channels

def list_lusers(c, e):
    for luser in filter(lambda n: n.startswith(NAME), e.arguments[-1].split(' ')):
        if luser not in lusers:
            lusers.append(luser)
    if c.get_nickname() not in lusers:
        c.reconnect()
    lusers.sort()
luser.on_namreply = list_lusers
def luser_joins(c, e):
    if e.source.nick not in lusers:
        lusers.append(e.source.nick)
        lusers.sort()
luser.on_join = lambda c, e: e.source.startswith(NAME) and luser_joins(c, e)
def luser_quits(c, e):
    lusers.remove(e.source.nick)
luser.on_quit = lambda c, e: e.source.startswith(NAME) and luser_quits(c, e)

last_lines = {}
def on_pubmsg(c, e):
    my_nick = c.get_nickname()
    nick = e.source.nick
    if nick.startswith(NAME): return
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
        if 'http' in msg:
            return c.privmsg(e.target, title(msg))

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
            return c.privmsg(e.target, reply[:512 - len(e.target) - 50])
luser.on_pubmsg = on_pubmsg

def post_source():
    try:
        from http.client import HTTPConnection
    except ImportError:
        from httplib import HTTPConnection
    conn = HTTPConnection('ix.io')
    conn.request('POST', '/', 'f:1=' + quote(open(__file__).read()))
    return conn.getresponse().read().decode().strip()

def google(text):
    import json
    with urlopen('https://ajax.googleapis.com/ajax/services/search/web?v=1.0&rsz=1&q=' + quote(text)) as r:
        data = json.loads(r.read().decode())['responseData']
        if not data['results']:
            return '0 result'
        return data['results'][0]['titleNoFormatting'] + ' ' + data['results'][0]['unescapedUrl']

wolframalpha_key = ''
with open('wolframalpha_key') as f:
    wolframalpha_key = f.read()
def wolframalpha(text):
    import xml.etree.ElementTree as ET
    try:
      with urlopen('http://api.wolframalpha.com/v2/query?format=plaintext&appid={}&input={}'.format(wolframalpha_key, quote(text))) as r:
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
    except Exception as e:
      logger.error('Got exception', e)

def title(text):
    titles = []
    urls = filter(lambda w: w.startswith('http'), text.split())
    for u in urls:
        try:
            with urlopen(u) as r:
                title = BeautifulSoup(r.read(50000), 'html.parser').title
                if title: titles.append(title.string.replace('\n', '').strip())
        except HTTPError as e:
            logger.error(u, "causes", e)
            continue
    return ' / '.join(titles)

yandex_key = ''
with open('yandex_key') as f:
    yandex_key = f.read()
def translate(text):
    import json
    (lang, _, text) = text.partition(' ')
    if not text:
        return 'Missing text'
    try:
        with urlopen('https://translate.yandex.net/api/v1.5/tr.json/translate?key={}&text={}&lang={}'.format(yandex_key, quote(text), lang)) as r:
            data = json.loads(r.read().decode())
            return data['lang'] + ": " + data['text'][0]
    except HTTPError:
        return "Unsupported language or wrong key"


if __name__ == '__main__':
  setup_logging('ircbot.log', True, os.path.dirname(os.path.realpath(__file__)))
  luser.start()
