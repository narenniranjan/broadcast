import mumble
import ssl
import pydle
import tornado.platform.asyncio
import asyncio
import argparse
import json
from enum import Enum


def escape_nick(nick):
    return nick.replace("", "\u00AD")


class MsgType(Enum):
    TEXT = 1
    ACTION = 2
    NICK = 3
    JOIN = 4
    PART = 5


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


class IRCClient(pydle.Client):
    def __init__(self, bus, nick, channel):
        self.bus = bus
        self.channel = channel
        self.bus.add_listener(self.on_bus_message)
        super().__init__(nick)

    def on_connect(self):
        self.join(self.channel)

    def on_join(self, channel, user):
        self.bus.broadcast(self, user, channel, MsgType.JOIN)

    def on_part(self, channel, user, reason):
        self.bus.broadcast(self, user, channel, MsgType.PART)

    def on_quit(self, user, reason):
        self.bus.broadcast(self, user, self.channel, MsgType.PART)

    def on_message(self, source, target, message):
        self.bus.broadcast(self, target, message, MsgType.TEXT)

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        author = escape_nick(author)
        if msg_type == MsgType.TEXT:
            self.message(
                self.channel, "\x02{}:\x02 {}".format(author, message))
        elif msg_type == MsgType.ACTION:
            self.message(
                self.channel, "*{} {}*".format(author, message))
        elif msg_type == MsgType.NICK:
            self.message(
                self.channel, "{} is now known as {}".format(author, message))
        elif msg_type == MsgType.JOIN:
            self.message(
                self.channel, ">>> {} has joined {}".format(author, message))
        elif msg_type == MsgType.PART:
            self.message(
                self.channel, "<<< {} has left {}".format(author, message))


class MumbleClient(mumble.Client):
    def __init__(self, bus, channel_id):
        self.bus = bus
        self.channel_id = channel_id
        self.bus.add_listener(self.on_bus_message)
        super().__init__()

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
        self.bus.broadcast(self, origin.name, message, MsgType.TEXT)

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        if msg_type == MsgType.TEXT:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "<b>{}:</b> {}".format(author, message))
        elif msg_type == MsgType.ACTION:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "<i>{} {}</i>".format(author, message))
        elif msg_type == MsgType.NICK:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "<i>{} is now known as {}</i>".format(author, message))
        elif msg_type == MsgType.JOIN:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "{} has joined {}".format(author, message))
        elif msg_type == MsgType.PART:
            self.send_text_message(
                    self.channels[self.channel_id],
                    "{} has left {}".format(author, message))

if __name__ == "__main__":
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

    tornado.platform.asyncio.AsyncIOMainLoop().install()
    loop = asyncio.get_event_loop()

    bus = Bus()

    for service in config:
        if service['type'] == 'irc':
            irc_client = IRCClient(bus, service['nick'], service['channel'])
            irc_client.connect(
                        service['server'], service['port'],
                        tls=bool(service['tls']),
                        tls_verify=bool(service['tls_verify']))
            running_services.append(irc_client)
        if service['type'] == 'mumble':
            mumble_client = MumbleClient(bus, service['channel_id'])
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
