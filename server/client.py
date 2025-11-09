from atproto import Client

from server import config


client = Client()
client.login(config.HANDLE, config.APP_PASS)

