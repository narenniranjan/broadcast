import pydle
from util import escape_nick, is_command, MsgType


# Pydle class that implements the bus interface.
class IRCClient(pydle.Client):
    def __init__(self, name, bus, cmd, nick, channel, nickpass,
                 prefix='I', enable_prefixes=True, enable_joinparts=True):
        self.name = name
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.channel = channel
        self.nickpass = nickpass
        self.enable_prefixes = enable_prefixes
        self.enable_joinparts = enable_joinparts

        self.cmd.add_client(self)
        self.bus.add_listener(self.on_bus_message)

        super().__init__(nick)

    # Modifications to allow autorejoin

    def connect(self, hostname=None, port=None, tls=False, **kwargs):
        super().connect(hostname, port, tls, **kwargs)
        self.eventloop.schedule_periodically(10, self.rejoin_channel)

    def rejoin_channel(self):
        if not self.in_channel(self.channel):
            self.logger.warning('Joining {}'.format(self.channel))
            self.join(self.channel)

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

    def on_invite(self, channel, by):
        if not self.in_channel(self.channel) and channel.lower() == self.channel.lower():
            self.logger.warning('Got invite from {} to join {}'.format(by, channel))
            self.join(self.channel)

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
            if not self.enable_joinparts:
                return
            msg = "[{}] >>> \x02{}\x02 has joined \x02{}\x02".format(source.prefix, author, message)[:400]

        elif msg_type == MsgType.PART:
            if not self.enable_joinparts:
                return
            msg = "[{}] <<< \x02{}\x02 has left \x02{}\x02".format(source.prefix, author, message)[:400]

        if not self.enable_prefixes:
            msg = msg[len(source.prefix) + 3:]

        self.message(self.channel, msg)
