import mumble
import discord
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
    return nick.replace("", "\u200D")


def strip_html(html):
    return bs4.BeautifulSoup(html).text


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

    def get_prefixes(self):
        return ", ".join(
                ["{}: {}".format(key, val.name)
                    for key, val in self.clients.items()])


# Discord.py class that implements the bus interface
class DiscordClient(discord.Client):
    def __init__(self, name, bus, cmd, channel, prefix):
        self.name = name
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.cmd.add_client(self)
        self.channel_id = channel
        self.channel = discord.Object(id=self.channel_id)
        self.bus.add_listener(self.on_bus_message)
        super().__init__()

    # special utility functions
    def fix_message(self, message):
        sanitized_content = message.clean_content.replace('\n', ' ')
        sanitized_content = sanitized_content.replace('\r', ' ')
        # this entire function is basically copypasta'd from
        # https://github.com/moeIO/michiru/blob/master/michiru/transports/discord.py#L110
        # thx Shiz
        try:
            for user in message.mentions:
                sanitized_content = sanitized_content.replace(
                            '@{}'.format(user.display_name),
                            '@' + user.display_name)
            return sanitized_content
        except AttributeError:
            return sanitized_content

    # common utility functions
    def get_user_list(self):
        channel = self.get_channel(self.channel_id)
        return [str(member.name) for member in channel.server.members]

    def get_topic(self):
        channel = self.get_channel(self.channel_id)
        return channel.topic

    def handle_command(self, author, message):
        args = message.split(' ')
        if args[0] == '.list':
            users = self.cmd.get_users(args[1])

            if users:
                msg = '**Users:** ' + ', '.join(users)

            else:
                msg = 'Please enter the prefix of the room to get the user list of.'

            asyncio.ensure_future(self.send_message(author, msg))
        elif args[0] == '.topic':
            topic = self.cmd.get_topic(args[1])
            if topic and topic != "":
                msg = '**Topic:** ' + topic

            elif topic == "":
                msg = 'That room has no topic.'

            else:
                msg = 'Please enter the prefix of the room to get the topic of.'

            asyncio.ensure_future(self.send_message(author, msg))

        elif args[0] == '.prefixes' or args[0] == '.prefix':
            asyncio.ensure_future(self.send_message(author, self.cmd.get_prefixes()))

    # callbacks
    @asyncio.coroutine
    def on_message(self, message):
        sanitized_content = self.fix_message(message)
        if message.channel.id == self.channel_id \
                and message.author != self.user:
            if is_command(sanitized_content):
                self.handle_command(message.author, sanitized_content)
            else:
                if message.author.nick:
                    self.bus.broadcast(
                            self, str(message.author.nick),
                            sanitized_content, MsgType.TEXT)
                else:
                    self.bus.broadcast(
                            self, str(message.author.name),
                            sanitized_content, MsgType.TEXT)
        # TODO: make this check that the message sending user shares servers
        # with the bot
        if message.channel.is_private:
            if is_command(sanitized_content):
                self.handle_command(message.author, sanitized_content)
        return

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        if msg_type == MsgType.TEXT:
            msg = "[{}] **{}:** {}".format(source.prefix, author, message)

        if msg_type == MsgType.ACTION:
            msg = "[{}] *{} {}*".format(source.prefix, author, message)

        if msg_type == MsgType.NICK:
            msg = "[{}] *{} is now known as {}*".format(source.prefix, author, message)

        if msg_type == MsgType.JOIN:
            msg = "[{}] >>> **{}** has joined **{}**".format(source.prefix, author, message)

        if msg_type == MsgType.PART:
            msg = "[{}] <<< **{}** has left **{}**".format(source.prefix, author, message)

        asyncio.ensure_future(self.send_message(self.channel, msg))
        return


# Pydle class that implements the bus interface.
class IRCClient(pydle.Client):
    def __init__(self, name, bus, cmd, nick, channel, prefix, nickpass):
        self.name = name
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.cmd.add_client(self)
        self.channel = channel
        self.bus.add_listener(self.on_bus_message)
        self.nickpass = nickpass
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
                msg = '\x02Users:\x02 ' + ', '.join(users)

            else:
                msg = 'Please enter the prefix of the room to get the user list of.'

        elif args[0] == '.topic':
            topic = self.cmd.get_topic(args[1])

            if topic and topic != "":
                msg = '\x02Topic:\x02 ' + topic

            elif topic == "":
                msg = 'That room has no topic.'

            else:
                msg = 'Please enter the prefix of the room to get the topic of.'

        elif args[0] == '.prefixes' or args[0] == '.prefix':
            msg = self.cmd.get_prefixes()

        self.notice(author, msg)

    # callbacks
    def on_connect(self):
        super().on_connect()
        if self.nickpass:
            self.message("NickServ", "IDENTIFY {}".format(self.nickpass))
        self.join(self.channel)

    def on_join(self, channel, user):
        self.bus.broadcast(self, user, channel, MsgType.JOIN)

    def on_part(self, channel, user, reason):
        self.bus.broadcast(self, user, channel, MsgType.PART)

    def on_quit(self, user, reason):
        self.bus.broadcast(self, user, self.channel, MsgType.PART)

    def on_ctcp_action(self, by, target, contents):
        self.bus.broadcast(self, by, contents, MsgType.ACTION)

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
            msg = "[{}] \x02{}:\x02 {}".format(source.prefix, author, message)[:400]

        elif msg_type == MsgType.ACTION:
            msg = "[{}] *\x02{}\x02 {}*".format(source.prefix, author, message)[:400]

        elif msg_type == MsgType.NICK:
            msg = "[{}] \x02{}\x02 is now known as \x02{}\x02".format(source.prefix, author, message)[:400]

        elif msg_type == MsgType.JOIN:
            msg = "[{}] >>> \x02{}\x02 has joined \x02{}\x02".format(source.prefix, author, message)[:400]

        elif msg_type == MsgType.PART:
            msg = "[{}] <<< \x02{}\x02 has left \x02{}\x02".format(source.prefix, author, message)[:400]

        self.message(self.channel, msg)


# python-mumble class that impelements the bus interface
class MumbleClient(mumble.Client):
    def __init__(self, name, bus, cmd, channel_id, prefix):
        self.name = name
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
                msg = '<b>Users:</b> ' + ', '.join(users)

            else:
                msg = 'Please enter the prefix of the room to get the user list of.'

        elif args[0] == '.topic':
            topic = self.cmd.get_topic(args[1])
            if topic and topic != "":
                msg = '<b>Topic:</b> ' + linkify(topic)

            elif topic:
                msg = 'That room has no topic.'

            else:
                msg = 'Please enter the prefix of the room to get the topic of.'

        elif args[0] == '.prefixes' or args[0] == '.prefix':
            msg = self.cmd.get_prefixes()

        self.send_text_message(origin, msg)

    # callbacks
    def connection_ready(self):
        self.join_channel(self.channels[self.channel_id])

    def user_moved(self, user, source, dest):
        if source and source == self.me.get_channel():
            self.bus.broadcast(self, user.name, self.me.get_channel().name, MsgType.PART)

        if dest and dest == self.me.get_channel():
            self.bus.broadcast(self, user.name, self.me.get_channel().name, MsgType.JOIN)

    def text_message_received(self, origin, target, message):
        if is_command(message):
            self.handle_command(origin, message)

        else:
            self.bus.broadcast(self, origin.name, strip_html(message), MsgType.TEXT)

    def on_bus_message(self, source, author, message, msg_type):
        if self == source:
            return
        if msg_type == MsgType.TEXT:
            msg = "[{}] <b>{}:</b> {}".format(source.prefix, author, linkify(message))

        elif msg_type == MsgType.ACTION:
            msg = "[{}] <i><b>{}</b> {}</i>".format(source.prefix, author, linkify(message))

        elif msg_type == MsgType.NICK:
            msg = "[{}] <i><b>{}</b> is now known as <b>{}</b></i>".format(source.prefix, author, message)

        elif msg_type == MsgType.JOIN:
            msg = "[{}] <b>{}</b> has joined <b>{}</b>".format(source.prefix, author, message)

        elif msg_type == MsgType.PART:
            msg = "[{}] <b>{}</b> has left <b>{}</b>".format(source.prefix, author, message)

        self.send_text_message(self.channels[self.channel_id], msg)

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
            try:
                nickpass = service['nickpass']
            except KeyError:
                nickpass = None
            irc_client = IRCClient(
                                service['name'], bus, cmd, service['nick'],
                                service['channel'], service['prefix'],
                                nickpass)
            irc_client.connect(
                        service['server'], service['port'],
                        tls=bool(service['tls']),
                        tls_verify=bool(service['tls_verify']))
            running_services.append(irc_client)
        if service['type'] == 'mumble':
            mumble_client = MumbleClient(
                                    service['name'], bus, cmd,
                                    service['channel_id'], service['prefix'])
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
        if service['type'] == 'discord':
            discord_client = DiscordClient(
                                    service['name'], bus, cmd,
                                    service['channel'], service['prefix'])
            discord_client.run(service['token'])
            running_services.append(discord_client)
    loop.run_forever()
