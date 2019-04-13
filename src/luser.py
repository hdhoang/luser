#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# external batteries
from bs4 import BeautifulSoup
from irc import bot
from ib3 import auth

from collections import defaultdict
from random import randint
from gzip import GzipFile
import xml.etree.ElementTree as ET
import json
import sys
import os

if sys.version_info.major == 3:
    from urllib.request import urlopen, build_opener, HTTPCookieProcessor
    from urllib.parse import quote
    from http.client import HTTPConnection
else:
    from urllib2 import urlopen, quote, build_opener, HTTPCookieProcessor
    from httplib import HTTPConnection
    from StringIO import StringIO
    reload(sys)
    sys.setdefaultencoding('utf8')

# Set up logging.

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
    file_log.setFormatter(logging.Formatter(
        '%(asctime)-15s (%(name)s) %(message)s'))
    logger.addHandler(file_log)

NAME = "luser"
PASSWORD = os.environ["FREENODE_PASSWORD"]

class Luser(auth.SASL, bot.SingleServerIRCBot):
    pass
luser = Luser([("chat.freenode.net", 8000)],
              ident_password=PASSWORD,
              realname=NAME,
   	      nickname='{}-{}'.format(NAME, str(randint(0, 9))),
              channels=["#vnluser", "#luser-test"])

def main():
    setup_logging("luser.log")
    luser.start()

def change_nick(c, e):
    new_nick = '{}-{}'.format(NAME, str(randint(0, 9)))
    print("Changing nick to", new_nick)
    c.nick(new_nick)
luser.on_nicknameinuse = change_nick

luser.on_nickcollision = lambda c, _: c.reconnect()

def join_channels(c, e):
    c.join("#{}-test".format(NAME))
    c.join("#vn" + NAME)
luser.on_welcome = join_channels

def handling(c, e):
    return lusers[len(e.source) % len(lusers)] == c.get_nickname()

def handle(c, e, msg):
    try:
        titles = title(msg)
        if titles and handling(c, e):
            c.privmsg(e.target, titles)
        if msg[0] not in ('.', '!', ':'): return
        if msg[1:6] == 'tell ':
            source = e.source.nick
            (target, _, line) = msg[6:].partition(' ')
            return relay_msg[target.lower()].append((source, line))
        reply = ''
        if msg[1:3] == 'g ':
            reply = google(msg[3:])
        if msg[1:4] == 'wa ':
            reply = wolframalpha(msg[4:])
        if msg[1:4] == 'tr ':
            (lang, _, text) = msg[4:].partition(' ')
            reply = translate(lang, text)
        if reply:
            # Keep PRIVMSG under 512bytes
            c.privmsg(e.target, reply[:512 - len(e.target) - 50])
    except Exception as e:
        logger.error('"%s" causes: %s' % (msg, str(e)))

# List other lusers, and update that list when one joins or quits.
#    This list is used by the lusers to decide whether to handle
#    unaddressed messages. If the length of the IRC prefix
#    'nick!user@host' for a message indexes to its name, that luser
#    responses.

lusers = []
def list_lusers(c, e):
    for luser in filter(lambda n: n.startswith(NAME),
                              e.arguments[-1].split(' ')):
        if luser not in lusers:
            lusers.append(luser)
    lusers.sort()
luser.on_namreply = list_lusers

relay_msg = defaultdict(list) # dict<nick.lower(), [(source, line)]>
def relay(c, target, nick):
    for (source, line) in relay_msg[nick.lower()]:
        c.privmsg(target, "{}: <{}> {}".format(nick, source, line))
    del relay_msg[nick.lower()]
luser.on_nick = lambda c, e: relay(c, "#vnluser", e.target)

def luser_joins(e):
    if e.source.nick not in lusers:
        lusers.append(e.source.nick)
        lusers.sort()

def on_join(c, e):
    nick = e.source.nick
    if nick.startswith(NAME):
        return luser_joins(e)
    relay(c, e.target, nick)
luser.on_join = on_join

def on_quit(c, e):
    if e.source.startswith(NAME):
        try:
            lusers.remove(e.source.nick)
        except ValueError:
            logger.info('"%s" in not in "%s"' % (e.source.nick, lusers))
luser.on_quit = on_quit

# Actual message processing. Ignore the other lusers.

last_lines = defaultdict(list) # dict<nick, line>
def on_pubmsg(c, e):
    nick = e.source.nick
    if nick.startswith(NAME): return
    my_nick = c.get_nickname()
    msg = e.arguments[0]
    if msg == "report!":
        return c.privmsg(e.target, report())
    if msg.startswith('s/'):
        parts = msg.split('/')
        if (len(parts) >= 3 and handling(c, e)
            and parts[1] in last_lines[nick]):
            return c.privmsg(e.target, "{} meant: {}".format(
                nick, last_lines[nick].replace(parts[1], parts[2])))
    else:
        last_lines[nick] = msg
    addressed = msg.startswith(my_nick)
    if addressed or handling(c, e) or 'http' in msg:
        if addressed:
            msg = msg[len(my_nick) + 2:]  # remove addressing
            if msg.startswith('quit'): sys.exit()
            if msg.startswith('reload'):
                os.execl(sys.executable, sys.executable, __file__)
        handle(c, e, msg)
luser.on_pubmsg = on_pubmsg

def title(text):
    """
    Retrieve titles from URL in text.

    >>> len(title('no url here'))
    0

    TODO This case should ignore the 404.
    >>> print(title('https://hdhoang.space/404 https://hdhoang.space/')) # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
      ...
    urllib.error.HTTPError: HTTP Error 404: Not Found

    >>> print(title('https://hdhoang.space/luser.html https://hdhoang.space/luser.html'))
    IRC bot / IRC bot

    >>> print(title('http://www.nytimes.com/2016/01/26/business/marvin-minsky-pioneer-in-artificial-intelligence-dies-at-88.html'))
    Marvin Minsky, Pioneer in Artificial Intelligence, Dies at 88 - The New York Times

    >>> print(title('http://www.baomoi.com/bao-nhieu-tan-bot-trung-quoc-da-duoc-nhap-ve-lam-tra-o-long-tea-plus/c/18486151.epi'))
    Bao nhiêu tấn bột Trung Quốc đã được nhập về làm trà Ô long TEA Plus? - GĐ&XH;

    >>> print(title('http://news.zing.vn/chi-tiet-ban-do-cam-duong-dip-29-o-ha-noi-post574142.html'))
    Chi tiết bản đồ cấm đường dịp 2/9 ở Hà Nội - Thời sự - Zing.vn

    >>> print(title('https://www.facebook.com/photo.php?fbid=261863914155282&set=a.261860180822322.1073742015.100009950253866&type=3&theater')) # doctest: +ELLIPSIS
    Vo Thanh Thuy - Vo Thanh Thuy ... | Facebook

    >>> print(title('https://imgur.com/M18GYfw?r https://imgur.com/GUFyoUa?r'))
    Glorious new key cap set for my work keyboard! - Imgur
    """
    uninteresting = ["XKCDB: The: The #xkcd Quote Database", "Saturday Morning Breakfast Cereal", "Library Genesis"]
    titles = []
    urls = filter(lambda w: w.startswith('http'), text.split())
    for u in urls:
        request = build_opener(HTTPCookieProcessor())
        request.addheaders = [('Accept-Encoding', 'gzip'), ('User-Agent', 'Mozilla/5.0')]
        response = request.open(u)
        if response.info().get('Content-Encoding') == 'gzip':
            if sys.version_info.major == 3:
                response = GzipFile(fileobj=response)
            else:
                response = GzipFile(fileobj=StringIO(response.read()))
        title = BeautifulSoup(response.read(50000), 'html.parser').title
        response.close()
        if (title
            and 'Imgur:' not in title.string
            and title.string not in uninteresting):
            titles.append(title.string.replace('\n', '').strip())
    return ' / '.join(titles)

def wolframalpha(text):
    """
    Query WolframAlpha about text.

    >>> print(wolframalpha('mass of sol'))
    Input interpretation: Sun | mass / Result: 1.988435×10^30 kg  (kilograms) / Unit conversions: 4.383749×10^30 lb  (pounds) / 2.191874×10^27 sh tn  (short tons) / 1.988435×10^33 grams / 1 M_☉  (solar ma http://wolframalpha.com/?input=mass%20of%20sol

    Check URL encoding:
    >>> print(wolframalpha('4+6'))
    Input: 4+6 / Result: 10 / Number name: ten / Number line: Manipulatives illustration:  | + |  |  |  4 |  | 6 |  | 10 / Typical human computation times: age 6:  5.3 seconds  |  age 8:  2.6 seconds  |  age 10:  1.7 seconds  |   age 18:  0.93 seconds (ignoring concentration, repetition, variations in education, etc.) / 

    >>> print(wolframalpha('é'))
    Input interpretation: é  (character) / Visual form: Name: Latin small letter e with acute / Positions in alphabets: Czech | 9th letter (33rd letter from the end) Slovak | 12th letter (35th letter from http://wolframalpha.com/?input=%C3%A9
    """
    r = urlopen(
        'http://api.wolframalpha.com/v2/query?format=plaintext&appid=3JEW42-4XXE264A93&input='
        + quote(text))
    tree = ET.parse(r)
    reply = ''
    for n in tree.iter():
        if n.tag == 'pod':
            reply += n.attrib['title'] + ': '
        if n.tag == 'plaintext' and n.text and len(n.text.strip()):
            reply += n.text + ' / '
    if len(reply) > 512:
        reply = reply[:200] + " http://wolframalpha.com/?input=" + quote(text)
    r.close()
    return reply.replace('\n', ' ')

def google(text):
    """
    Retrieve the first result from a google for text.

    >>> print(google('á'))
    Á - Wikipedia, the free encyclopedia https://en.wikipedia.org/wiki/%C3%81

    >>> print(google('trump south-china sea'))
    Donald Trump weighs in on China's island-building in the South ... http://www.politifact.com/truth-o-meter/statements/2016/apr/04/donald-trump/donald-trump-weighs-chinas-island-building-south-c/

    >>> print(google('naesuth no result here'))
    0 result
    """
    r = urlopen(
        'https://www.googleapis.com/customsearch/v1?key=AIzaSyDuesDCP1pqw6Ev_3zEAG4xuIKYp675oDw&cx=002790383760335821747:hufomuuaviw&q=' +
        quote(text))
    data = json.loads(r.read().decode())
    r.close()
    if 'items' not in data:
        return '0 result'
    return data['items'][0]['title'] + \
    ' ' +  data['items'][0]['link']

def translate(direction, text):
    """
    Translate text according to direction.

    >>> print(translate('la-en', 'ad astra per aspera'))
    la-en: to the stars through rough

    >>> print(translate('vi', "you think you're good?"))
    en-vi: ngươi nghĩ ngươi giỏi không?

    >>> print(translate('en', 'mày nghĩ mày ngon?'))
    vi-en: you think you're so tough?

    >>> print(translate('jbo', 'hello')) # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
      ...
    urllib.error.HTTPError: HTTP Error 400: BAD REQUEST
    """
    if not text:
        return 'Missing text'
    r = urlopen(
        'https://translate.yandex.net/api/v1.5/tr.json/translate?key=trnsl.1.1.20160210T093900Z.c6eacf09bbb65cfb.cc28de2ba798bc3bc118e9f8201b6e6cea697810&text={}&lang={}'
        .format(
            quote(text), direction))
    data = json.loads(r.read().decode())
    r.close()
    return data['lang'] + ": " + data['text'][0]

def report():
    """
    Return owner and source code

    >>> print(report()) # doctest: +ELLIPSIS
    operated by ... with source code http://ix.io/...
    """
    conn = HTTPConnection('ix.io')
    conn.request(
        'POST', '/',
        'read:1=3&name:1=luser.py&f:1=' + quote(open(__file__).read()))
    return "operated by {} with source code {}".format(
            os.getenv('USER'), conn.getresponse().read().decode().strip())

if __name__ == '__main__':
    main()
