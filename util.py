import bs4
import re
from enum import Enum


def escape_nick(nick):
    return "\u200D".join(nick)


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
    try:
        return msg[0] == '.'
    except IndexError:
        return False


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
