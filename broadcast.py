import mumble
import ssl
import pydle
import tornado.platform.asyncio
import asyncio
import argparse
import json
import re
import bs4
from enum import Enum


def escape_nick(nick):
    return nick.replace("", "\u00AD")


def strip_html(html):
    return bs4.BeautifulSoup(html, "lxml").text


def linkify(url):
    # Replace url to link
    urls = re.compile(
            r"((https?):((//)|(\\\\))+[\w\d:#@%/;$()~_?\+-=\\\.&]*)",
            re.MULTILINE | re.UNICODE)
    url = urls.sub(r'<a href="\1" target="_blank">\1</a>', url)
    # Replace email to mailto
    urls = re.compile(
            r"([\w\-\.]+@(\w[\w\-]+\.)+[\w\-]+)", re.MULTILINE | re.UNICODE)
    url = urls.sub(r'<a href="mailto:\1">\1</a>', url)
    return url


def is_command(msg):
    return msg[0] == '.'


# enum to allow determining the type of a message
class MsgType(Enum):
    TEXT = 1
    ACTION = 2
    NICK = 3
    JOIN = 4
    PART = 5


# message passing bus
class Bus(object):
    def __init__(self):
        self.listeners = set()

    def add_listener(self, listener):
        self.listeners.add(listener)

    def remove_listener(self, listener):
        self.listeners.remove(listener)

    def broadcast(self, *args, **kwargs):
        for listener in self.listeners:
            listener(*args, **kwargs)


# maintains a list of client prefix -> client mappings to allow for
# simple commands that depend on another client (such as user listing)
class CommandProcessor(object):
    def __init__(self):
        self.clients = dict()

    def add_client(self, client):
        self.clients[client.prefix] = client

    def remove_client(self, client):
        self.clients.pop(client.prefix)

    def get_users(self, prefix):
        try:
            client = self.clients[prefix]
        except KeyError:
            return []
        return client.get_user_list()

    def get_topic(self, prefix):
        try:
            client = self.clients[prefix]
        except KeyError:
            return None
        return client.get_topic()


# Pydle class that implements the bus interface.
class IRCClient(pydle.Client):
    def __init__(self, bus, cmd, nick, channel, prefix):
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.cmd.add_client(self)
        self.channel = channel
        self.bus.add_listener(self.on_bus_message)
        super().__init__(nick)

    # common utility functions
    def get_user_list(self):
        return [i for i in self.channels[self.channel]['users']]

    def get_topic(self):
        return self.channels[self.channel]['topic']

    def handle_command(self, author, message):
        args = message.split(' ')
        if args[0] == '.list':
            users = self.cmd.get_users(args[1])
            if users:
                self.notice(author, '\x02Users:\x02 ' + ', '.join(users))
            else:
                self.notice(author, 'Please enter the prefix of the '
                                    'room to get the user list of.')
        elif args[0] == '.topic':
            topic = self.cmd.get_topic(args[1])
            if topic and topic != "":
                self.notice(author, '\x02Topic:\x02 ' + topic)
            elif topic == "":
                self.notice(author, 'That room has no topic.')
            else:
                self.notice(author, 'Please enter the prefix of the '
                                    'room to get the topic of.')

    # callbacks
    def on_connect(self):
        self.join(self.channel)

    def on_join(self, channel, user):
        self.bus.broadcast(self, user, channel, MsgType.JOIN)

    def on_part(self, channel, user, reason):
        self.bus.broadcast(self, user, channel, MsgType.PART)

    def on_quit(self, user, reason):
        self.bus.broadcast(self, user, self.channel, MsgType.PART)

    def irc_action(self, origin, action):
        self.bus.broadcast(self, origin, action, MsgType.ACTION)

    def on_nick_change(self, old, new):
        self.bus.broadcast(self, old, new, MsgType.NICK)

    def on_message(self, source, target, message):
        if is_command(message):
            self.handle_command(target, message)
        else:
            self.bus.broadcast(self, target, message, MsgType.TEXT)

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        author = escape_nick(author)
        if msg_type == MsgType.TEXT:
            self.message(
                self.channel, "[{}] \x02{}:\x02 {}".format(
                                                        source.prefix,
                                                        author, message))
        elif msg_type == MsgType.ACTION:
            self.message(
                self.channel, "[{}] *\x02{}\x02 {}*".format(
                                                source.prefix,
                                                author, message))
        elif msg_type == MsgType.NICK:
            self.message(
                self.channel,
                "[{}] \x02{}\x02 is now known as \x02{}\x02".format(
                                                            source.prefix,
                                                            author, message))
        elif msg_type == MsgType.JOIN:
            self.message(
                self.channel,
                "[{}] >>> \x02{}\x02 has joined \x02{}\x02".format(
                                                            source.prefix,
                                                            author, message))
        elif msg_type == MsgType.PART:
            self.message(
                self.channel,
                "[{}] <<< \x02{}\x02 has left \x02{}\x02".format(
                                                            source.prefix,
                                                            author, message))


# python-mumble class that impelements the bus interface
class MumbleClient(mumble.Client):
    def __init__(self, bus, cmd, channel_id, prefix):
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.cmd.add_client(self)
        self.channel_id = channel_id
        self.bus.add_listener(self.on_bus_message)
        super().__init__()

    # common utility functions
    def get_user_list(self):
        return [self.users[x].name
                for x in self.users
                if self.users[x].channel_id == self.channel_id]

    def get_topic(self):
        return ""

    def handle_command(self, origin, message):
        args = message.split(' ')
        if args[0] == '.list':
            users = self.cmd.get_users(args[1])
            if users:
                self.send_text_message(
                                    origin,
                                    '<b>Users:</b> ' + ', '.join(users))
            else:
                self.send_text_message(origin, 'Please enter the prefix of the'
                                       ' room to get the user list of.')
        elif args[0] == '.topic':
            topic = self.cmd.get_topic(args[1])
            if topic and topic != "":
                self.send_text_message(
                                origin,
                                '<b>Topic:</b> ' + linkify(topic))
            elif topic:
                self.send_text_message(origin, 'That room has no topic.')
            else:
                self.send_text_message(origin, 'Please enter the prefix of the'
                                       ' room to get the topic of.')

        return

    # callbacks
    def connection_ready(self):
        self.join_channel(self.channels[self.channel_id])

    def user_moved(self, user, source, dest):
        if source and source == self.me.get_channel():
            self.bus.broadcast(
                        self, user.name,
                        self.me.get_channel().name, MsgType.PART)
        if dest and dest == self.me.get_channel():
            self.bus.broadcast(
                        self, user.name,
                        self.me.get_channel().name, MsgType.JOIN)

    def text_message_received(self, origin, target, message):
        if is_command(message):
            self.handle_command(origin, message)
        else:
            self.bus.broadcast(
                        self, origin.name, strip_html(message), MsgType.TEXT)

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        if msg_type == MsgType.TEXT:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "[{}] <b>{}:</b> {}".format(
                                            source.prefix,
                                            author, linkify(message)))
        elif msg_type == MsgType.ACTION:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "[{}] <i><b>{}</b> {}</i>".format(
                                            source.prefix,
                                            author, linkify(message)))

        elif msg_type == MsgType.NICK:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "[{}] <i><b>{}</b> is now known as <b>{}</b></i>".format(
                                                            source.prefix,
                                                            author, message))
        elif msg_type == MsgType.JOIN:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "[{}] <b>{}</b> has joined <b>{}</b>".format(
                                                source.prefix,
                                                author, message))
        elif msg_type == MsgType.PART:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "[{}] <b>{}</b> has left <b>{}</b>".format(
                                                source.prefix,
                                                author, message))

if __name__ == "__main__":
    # list of the running services
    running_services = []

    arg_parse = argparse.ArgumentParser()
    arg_parse.add_argument(
            '--config',
            required=False,
            help='Location of config file')
    args = arg_parse.parse_args()

    if args.config:
        f = open(args.config, 'r')
    else:
        f = open('config.json', 'r')
    config = json.load(f)
    f.close()

    # this lets us use pydle (which uses tornado) with
    # python-mumble (which uses asyncio)
    tornado.platform.asyncio.AsyncIOMainLoop().install()
    loop = asyncio.get_event_loop()

    # message bus, allows the different clients to communicate
    # with one another
    bus = Bus()

    # For user/topic listing and possibly additional commands
    cmd = CommandProcessor()

    # actually load and run the clients
    for service in config:
        if service['type'] == 'irc':
            irc_client = IRCClient(
                                bus, cmd, service['nick'],
                                service['channel'], service['prefix'])
            irc_client.connect(
                        service['server'], service['port'],
                        tls=bool(service['tls']),
                        tls_verify=bool(service['tls_verify']))
            running_services.append(irc_client)
        if service['type'] == 'mumble':
            mumble_client = MumbleClient(
                                    bus, cmd, service['channel_id'],
                                    service['prefix'])
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            if 'cert' in service and 'certpw' in service:
                ssl_ctx.load_cert_chain(
                                service['cert'], None, service['certpw'])
            loop.run_until_complete(
                    mumble_client.connect(
                        service['server'], service['port'], service['nick'],
                        service['password'], ssl_ctx))
            running_services.append(mumble_client)
    loop.run_forever()
