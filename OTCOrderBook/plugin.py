###
# OTCOrderBook - supybot plugin to keep an order book from irc
# Copyright (C) 2010, Daniel Folkinshteyn <nanotube@users.sourceforge.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
from supybot import conf
from supybot import ircdb

import sqlite3
import time
import os.path
import re
import json

class OTCOrderDB(object):
    def __init__(self, filename):
        self.filename = filename
        self.db = None

    def open(self):
        if os.path.exists(self.filename):
            db = sqlite3.connect(self.filename, check_same_thread = False)
            db.text_factory = str
            self.db = db
            return
        
        db = sqlite3.connect(self.filename, check_same_thread = False)
        db.text_factory = str
        self.db = db
        cursor = self.db.cursor()
        cursor.execute("""CREATE TABLE orders (
                          id INTEGER PRIMARY KEY,
                          created_at INTEGER,
                          refreshed_at INTEGER,
                          buysell TEXT,
                          nick TEXT,
                          host TEXT,
                          amount REAL,
                          thing TEXT,
                          price TEXT,
                          otherthing TEXT,
                          notes TEXT)
                          """)
        self.db.commit()
        return

    def close(self):
        self.db.close()

    def get(self, nick=None, id=None):
        cursor = self.db.cursor()
        sql = "SELECT * FROM orders WHERE"
        joiner = ""
        vars = []
        if id is None and nick is None:
            return []
        if nick is not None:
            sql += " nick LIKE ?"
            vars.append(nick)
            joiner = " AND"
        if id is not None:
            sql += joiner + " id=?"
            vars.append(id)
        cursor.execute(sql, tuple(vars))
        return cursor.fetchall()

    def getByNick(self, nick):
        cursor = self.db.cursor()
        cursor.execute("""SELECT * FROM orders WHERE nick LIKE ?""", (nick,))
        return cursor.fetchall()

    def getById(self, id):
        cursor = self.db.cursor()
        cursor.execute("""SELECT * FROM orders WHERE id=?""", (id,))
        return cursor.fetchall()

    def deleteExpired(self, expiry):
        cursor = self.db.cursor()
        timestamp = time.time()
        cursor.execute("""DELETE FROM orders WHERE refreshed_at + ? < ?""",
                       (expiry, timestamp))
        self.db.commit()

    def getCurrencyBook(self, thing):
        cursor = self.db.cursor()
        cursor.execute("""SELECT * FROM orders WHERE thing LIKE ?
                       OR otherthing LIKE ?
                       ORDER BY price""",
                       (thing, thing))
        return cursor.fetchall()

    def buy(self, nick, host, amount, thing, price, otherthing, notes):
        cursor = self.db.cursor()
        timestamp = time.time()
        cursor.execute("""INSERT INTO orders VALUES
                       (NULL, ?, ?, "BUY", ?, ?, ?, ?, ?, ?, ?)""",
                       (timestamp, timestamp, nick, host, amount, thing, price,
                        otherthing, notes))
        self.db.commit()
        return cursor.lastrowid

    def sell(self, nick, host, amount, thing, price, otherthing, notes):
        cursor = self.db.cursor()
        timestamp = time.time()
        cursor.execute("""INSERT INTO orders VALUES
                       (NULL, ?, ?, "SELL", ?, ?, ?, ?, ?, ?, ?)""",
                       (timestamp, timestamp, nick, host, amount, thing, price,
                        otherthing, notes))
        self.db.commit()
        return cursor.lastrowid

    def refresh(self, nick, id=None):
        results = self.get(nick, id)
        if len(results) != 0:
            cursor = self.db.cursor()
            timestamp = time.time()
            for row in results:
                cursor.execute("""UPDATE orders SET refreshed_at=?
                               WHERE id=?""", (timestamp, row[0]))
            self.db.commit()
            return len(results)
        return False

    def remove(self, nick, id=None):
        results = self.get(nick, id)
        if len(results) != 0:
            cursor = self.db.cursor()
            for row in results:
                cursor.execute("""DELETE FROM orders where id=?""",
                               (row[0],))
            self.db.commit()
            return len(results)
        return False
    
def getAt(irc, msg, args, state):
    if args[0].lower() in ['at', '@']:
        args.pop(0)

#def getBTC(irc, msg, args, state):
#    if args[0].lower() in ['btc','bitcoin','bitcoins']:
#        args.pop(0)

def getIndexedPrice(irc, msg, args, state, type='price input'):
    """Indexed price can contain one or more of {mtgoxask}, {mtgoxbid},
    {mtgoxlast}, included in an arithmetical expression.
    It can also contain one expression of the form {XXX in YYY} which
    queries google for currency conversion rate from XXX to YYY."""
    try:
        v = args[0]
        v = re.sub(r'{mtgoxask}|{mtgoxbid}|{mtgoxlast}', '1', v)
        v = re.sub(r'{... in ...}', '1', v, 1)
        if not set(v).issubset(set('1234567890*-+./() ')) or '**' in v:
            raise ValueError, "only {mtgoxask}, {mtgoxbid}, {mtgoxlast}, one {... in ...}, and arithmetic allowed."
        eval(v)
        state.args.append(args[0])
        del args[0]
    except:
        state.errorInvalid(type, args[0])

def getPositiveFloat(irc, msg, args, state, type='positive floating point number'):
    try:
        v = float(args[0])
        if v <= 0:
            raise ValueError, "only positive numbers allowed."
        state.args.append(v)
        del args[0]
    except ValueError:
        state.errorInvalid(type, args[0])

def getNonNegativeFloat(irc, msg, args, state, type=' floating point number'):
    try:
        v = float(args[0])
        if v < 0:
            raise ValueError, "only non-negative numbers allowed."
        state.args.append(v)
        del args[0]
    except ValueError:
        state.errorInvalid(type, args[0])

addConverter('at', getAt)
addConverter('positiveFloat', getPositiveFloat)
addConverter('nonNegativeFloat', getNonNegativeFloat)
addConverter('indexedPrice', getIndexedPrice)
#addConverter('btc', getBTC)

class OTCOrderBook(callbacks.Plugin):
    """This plugin maintains an order book for order entry over irc.
    Use commands 'buy' and 'sell' to enter orders.
    Use command 'renew' to renew your open orders.
    Use command 'remove' to cancel open orders.
    """
    threaded = True

    def __init__(self, irc):
        self.__parent = super(OTCOrderBook, self)
        self.__parent.__init__(irc)
        self.filename = conf.supybot.directories.data.dirize('OTCOrderBook.db')
        self.db = OTCOrderDB(self.filename)
        self.db.open()

    def die(self):
        self.__parent.die()
        self.db.close()

    def _checkGPGAuth(self, irc, prefix):
        return irc.getCallback('GPG')._ident(prefix)

    def _getMtgoxQuote(self):
        try:
            ticker = utils.web.getUrl('http://mtgox.com/code/ticker.php')
            self.ticker = json.loads(ticker, parse_float=str, parse_int=str)
            self.ticker = self.ticker['ticker']
        except:
            pass # don't want to die on failure of mtgox

    def _getCurrencyConversion(self, rawprice):
        conv = re.search(r'{(...) in (...)}', rawprice)
        if conv is None:
            return rawprice
        googlerate = self._queryGoogleRate(conv.group(1), conv.group(2))
        indexedprice = re.sub(r'{... in ...}', googlerate, rawprice)
        return indexedprice

    def _queryGoogleRate(self, cur1, cur2):
        googlerate = utils.web.getUrl('http://www.google.com/ig/calculator?hl=en&q=1%s=?%s' % \
                (cur1, cur2,))
        googlerate = re.sub(r'(\w+):', r'"\1":', googlerate) # badly formed json, missing quotes
        googlerate = json.loads(googlerate, parse_float=str, parse_int=str)
        if googlerate['error']:
            raise ValueError, googlerate['error']
        return googlerate['rhs'].split()[0]

    def _getIndexedValue(self, rawprice):
        try:
            indexedprice = re.sub(r'{mtgoxask}', self.ticker['sell'], rawprice)
            indexedprice = re.sub(r'{mtgoxbid}', self.ticker['buy'], indexedprice)
            indexedprice = re.sub(r'{mtgoxlast}', self.ticker['last'], indexedprice)
            indexedprice = self._getCurrencyConversion(indexedprice)
            return "%.5g" % eval(indexedprice)
        except:
            return '"' + rawprice + '"'

    def buy(self, irc, msg, args, amount, thing, price, otherthing, notes):
        """<amount> <thing> [at|@] <priceperunit> <otherthing> [<notes>]

        Logs a buy order for <amount> units of <thing>, at a price of <price>
        per unit, in units of <otherthing>. Use the optional <notes> field to
        put in any special notes. <price> may include an arithmetical expression,
        and {mtgox(ask|bid|last)} to index price to mtgox ask, bid, or last price.
        May also include expression of the form {... in ...} which queries google
        for a currency conversion rate between two currencies.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        gpgauth = self._checkGPGAuth(irc, msg.prefix)
        if gpgauth is None:
            irc.error("For identification purposes, you must be identified via GPG "
                      "to use the order book.")
            return
        results = self.db.getByNick(gpgauth['nick'])
        if len(results) >= self.registryValue('maxUserOpenOrders'):
            irc.error("You may not have more than %s outstanding open orders." % \
                      self.registryValue('maxUserOpenOrders'))
            return

        orderid = self.db.buy(gpgauth['nick'], msg.host, amount, thing, price, otherthing, notes)
        irc.reply("Order id %s created." % (orderid,))
    buy = wrap(buy, ['positiveFloat','something','at','indexedPrice','something',
                     optional('text')])

    def sell(self, irc, msg, args, amount, thing, price, otherthing, notes):
        """<amount> <thing> [at|@] <priceperunit> <otherthing> [<notes>]

        Logs a sell order for <amount> units of <thing, at a price of <price>
        per unit, in units of <otherthing>. Use the optional <notes> field to
        put in any special notes. <price> may include an arithmetical expression,
        and {mtgox(ask|bid|last)} to index price to mtgox ask, bid, or last price.
        May also include expression of the form {... in ...} which queries google
        for a currency conversion rate between two currencies.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        gpgauth = self._checkGPGAuth(irc, msg.prefix)
        if gpgauth is None:
            irc.error("For identification purposes, you must be identified via GPG "
                      "to use the order book.")
            return
        results = self.db.getByNick(gpgauth['nick'])
        if len(results) >= self.registryValue('maxUserOpenOrders'):
            irc.error("You may not have more than %s outstanding open orders." % \
                      self.registryValue('maxUserOpenOrders'))
            return

        orderid = self.db.sell(gpgauth['nick'], msg.host, amount, thing, price, otherthing, notes)
        irc.reply("Order id %s created." % (orderid,))
    sell = wrap(sell, ['positiveFloat','something','at','indexedPrice','something',
                     optional('text')])

    def refresh(self, irc, msg, args, orderid):
        """[<orderid>]

        Refresh the timestamps on your outstanding orders. If optional
        <orderid> argument present, only refreshes that particular order.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        gpgauth = self._checkGPGAuth(irc, msg.prefix)
        if gpgauth is None:
            irc.error("For identification purposes, you must be identified via GPG "
                      "to use the order book.")
            return
        rv = self.db.refresh(gpgauth['nick'], orderid)
        if rv is not False:
            irc.reply("Order refresh successful, %s orders refreshed." % rv)
        else:
            irc.error("No orders found to refresh. Try the 'view' command to "
                      "view your open orders.")
    refresh = wrap(refresh, [optional('int')])

    def remove(self, irc, msg, args, orderid):
        """[<orderid>]

        Remove your outstanding orders. If optional <orderid> argument present,
        only removes that particular order.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        gpgauth = self._checkGPGAuth(irc, msg.prefix)
        if gpgauth is None:
            irc.error("For identification purposes, you must be identified via GPG "
                      "to use the order book.")
            return
        rv = self.db.remove(gpgauth['nick'], orderid)
        if rv is not False:
            irc.reply("Order remove successful, %s orders removed." % rv)
        else:
            irc.error("No orders found to remove. Try the 'view' command to "
                      "view your open orders.")
    remove = wrap(remove, [optional('int')])

    def view(self, irc, msg, args, optlist, query):
        """[--raw] [<orderid>|<nick>]

        View information about your outstanding orders. If optional <orderid>
        or <nick> argument is present, only show orders with that id or nick.
        If '--raw' option is given, show raw price input, rather than the
        resulting indexed value.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        gpgauth = self._checkGPGAuth(irc, msg.prefix)
        raw = False
        for (option, arg) in optlist:
            if option == 'raw':
                raw = True
        if raw:
            f = lambda x: '"%s"' % x
        else:
            self._getMtgoxQuote()
            f = self._getIndexedValue
        if query is None:
            if gpgauth is None:
                nick = msg.nick
            else:
                nick = gpgauth['nick']
            results = self.db.getByNick(nick)
        elif isinstance(query, int):
            results = self.db.getById(query)
        else:
            nick = query
            results = self.db.getByNick(nick)
        if len(results) == 0:
            irc.error("No orders found matching these criteria.")
            return
        if len(results) > self.registryValue('maxOrdersInBookList'):
            irc.error("Too many orders to list on channel. Visit "
                    "http://bitcoin-otc.com/vieworderbook.php?nick=%s "
                    "to see the list of matching orders." % (nick,))
            return
        L = ["#%s %s %s %s %s %s @ %s %s (%s)" % (id,
                                                   time.ctime(refreshed_at),
                                                   nick,
                                                   buysell,
                                                   amount,
                                                   thing,
                                                   f(price),
                                                   otherthing,
                                                   notes) \
             for (id,
                  created_at,
                  refreshed_at,
                  buysell,
                  nick,
                  host,
                  amount,
                  thing,
                  price,
                  otherthing,
                  notes) in results]

        irc.replies(L, joiner=" || ")
    view = wrap(view, [getopts({'raw': '',}), optional(first('int','something'))])
    
    def book(self, irc, msg, args, thing):
        """<thing>

        Get a list of open orders for <thing>.
        """
        self.db.deleteExpired(self.registryValue('orderExpiry'))
        results = self.db.getCurrencyBook(thing)
        if len(results) == 0:
            irc.error("No orders for this currency present in database.")
            return
        if len(results) > self.registryValue('maxOrdersInBookList'):
            irc.error("Too many orders to list on channel. Visit the web "
                      "order book, http://bitcoin-otc.com/vieworderbook.php?eitherthing=%s "
                      "to see list of orders for this item." % (thing,))
            return
        self._getMtgoxQuote()
        L = ["#%s %s %s %s %s %s @ %s %s (%s)" % (id,
                                                      time.ctime(refreshed_at),
                                                      nick,
                                                      buysell,
                                                      amount,
                                                      thing,
                                                      self._getIndexedValue(price),
                                                      otherthing,
                                                      notes) \
             for (id,
                  created_at,
                  refreshed_at,
                  buysell,
                  nick,
                  host,
                  amount,
                  thing,
                  price,
                  otherthing,
                  notes) in results]
        irc.replies(L, joiner=" || ")
    book = wrap(book, ['something'])

Class = OTCOrderBook


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
