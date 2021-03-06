import asyncio
import discord
import re
from util import is_command, MsgType


# Discord.py class that implements the bus interface
class DiscordClient(discord.Client):
    def __init__(self, name, bus, cmd, channel, prefix='D', enable_joinparts=True, enable_prefixes=True):
        self.name = name
        self.bus = bus
        self.cmd = cmd
        self.prefix = prefix
        self.channel_id = channel
        self.channel = discord.Object(id=self.channel_id)
        self.enable_prefixes = enable_prefixes
        self.enable_joinparts = enable_joinparts

        self.cmd.add_client(self)
        self.bus.add_listener(self.on_bus_message)
        super().__init__()

    # special utility functions
    @staticmethod
    def fix_emojis(emoji_identifier):
        emoji_identifier = emoji_identifier.group(0)
        try:
            return ':{}:'.format(emoji_identifier[1:-1].split(':')[1])
        except:
            return emoji_identifier

    @staticmethod
    def fix_message(message):
        sanitized_content = message.clean_content.replace('\n', ' ')
        sanitized_content = sanitized_content.replace('\r', ' ')
        return sanitized_content

    def fix_pings(self, username):
        def match_username(user):
            if user.name == username[1:]:
                return True
            if user.nick is not None and user.nick == username[1:]:
                return True
            return False

        username = username.group(0)
        channel = self.get_channel(self.channel_id)
        member = discord.utils.find(match_username, channel.server.members)

        return member.mention if member is not None else username

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
        sanitized_content = DiscordClient.fix_message(message)

        # If there are attached files, append them to the sanitized message
        if len(message.attachments):
            for attachment in message.attachments:
                sanitized_content += " {}".format(attachment['url'])

        # If there are embeds, append their URLs to the message
        if len(message.embeds):
            for embed in message.embeds:
                sanitized_content += " {}".format(embed['url'])

        # Replace those ugly custom emoji strings with the name of the emoji
        sanitized_content = re.sub('<:\S+:\d+>', DiscordClient.fix_emojis, sanitized_content)

        if message.channel.id == self.channel_id \
                and message.author != self.user:
            if is_command(sanitized_content):
                self.handle_command(message.author, sanitized_content)
            else:
                if message.author.nick:
                    self.bus.broadcast(
                            self, '{} ({})'.format(str(message.author.name), str(message.author.nick)),
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
            if not self.enable_joinparts:
                return
            msg = "[{}] >>> **{}** has joined **{}**".format(source.prefix, author, message)

        if msg_type == MsgType.PART:
            if not self.enable_joinparts:
                return
            msg = "[{}] <<< **{}** has left **{}**".format(source.prefix, author, message)

        # Remove prefixes (this isn't ideal imo but the other way of handling prefix removal
        # was even more ugly, so this is the way I'm doing it
        if not self.enable_prefixes:
            msg = msg[len(source.prefix) + 3:]

        # Replace @user pings with actual pings
        msg = re.sub('@\S+', self.fix_pings, msg)

        asyncio.ensure_future(self.send_message(self.channel, msg))
        return
