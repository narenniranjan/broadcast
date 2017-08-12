import mumble
from util import is_command, linkify, strip_html, MsgType


# python-mumble class that impelements the bus interface
class MumbleClient(mumble.Client):
    def __init__(self, name, bus, cmd, channel_id, prefix='M', enable_prefixes=True, enable_joinparts=True):
        self.name = name
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.cmd.add_client(self)
        self.channel_id = channel_id
        self.enable_prefixes = enable_prefixes
        self.enable_joinparts = enable_joinparts
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
            if not self.enable_joinparts:
                return
            msg = "[{}] <b>{}</b> has joined <b>{}</b>".format(source.prefix, author, message)

        elif msg_type == MsgType.PART:
            if not self.enable_joinparts:
                return
            msg = "[{}] <b>{}</b> has left <b>{}</b>".format(source.prefix, author, message)

        if not self.enable_prefixes:
            msg = msg[len(source.prefix) + 3:]

        self.send_text_message(self.channels[self.channel_id], msg)
