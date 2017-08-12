import argparse
import asyncio
import json
import ssl
import tornado.platform.asyncio
from services.discord_client import DiscordClient
from services.irc_client import IRCClient
from services.mumble_client import MumbleClient
from util import Bus, CommandProcessor

global JOINPART, PREFIXES

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

    # Set globals based on config file
    JOINPART = config['enable_joinpart']
    PREFIXES = config['enable_prefixes']

    # actually load and run the clients
    for service in config['services']:
        if service['type'] == 'irc':
            try:
                nickpass = service['nickpass']
            except KeyError:
                nickpass = None
            irc_client = IRCClient(
                                service['name'], bus, cmd, service['nick'],
                                service['channel'], nickpass, prefix=service['prefix'],
                                enable_prefixes=PREFIXES, enable_joinparts=JOINPART)

            irc_client.connect(
                        service['server'], service['port'],
                        tls=bool(service['tls']),
                        tls_verify=bool(service['tls_verify']))

            running_services.append(irc_client)

        if service['type'] == 'mumble':
            mumble_client = MumbleClient(
                                    service['name'], bus, cmd,
                                    service['channel_id'], prefix=service['prefix'],
                                    enable_prefixes=PREFIXES, enable_joinparts=JOINPART)

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            if 'cert' in service and 'certpw' in service:
                ssl_ctx.load_cert_chain(service['cert'], None, service['certpw'])

            loop.run_until_complete(
                    mumble_client.connect(
                        service['server'], service['port'], service['nick'],
                        service['password'], ssl_ctx))
            running_services.append(mumble_client)

        if service['type'] == 'discord':
            discord_client = DiscordClient(
                                    service['name'], bus, cmd,
                                    service['channel'], prefix=service['prefix'],
                                    enable_prefixes=PREFIXES, enable_joinparts=JOINPART)
            discord_client.run(service['token'])
            running_services.append(discord_client)
    loop.run_forever()
