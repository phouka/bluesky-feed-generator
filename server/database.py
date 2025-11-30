from server import config
from datetime import datetime, timezone

import peewee

watch_lookup = {}
watch_list = {}

ignore_lookup = {}
ignore_list = {}

db = peewee.PostgresqlDatabase(config.DB_NAME, host='localhost', port=config.DB_PORT, user=config.DB_USER, password=config.DB_PASS)

class BaseModel(peewee.Model):
    class Meta:
        database = db

class Post(BaseModel):
    orig_uri = peewee.CharField(index=True)
    uri = peewee.CharField()
    cid = peewee.CharField()
    indexed_at = peewee.BigIntegerField(default=int(datetime.now(timezone.utc).timestamp() * 1000))

# this keeps track of where in the firehose the events were last read
# this allows the system to catch up to the stream after a restart
class SubscriptionState(BaseModel):
    service = peewee.CharField(unique=True)
    cursor = peewee.BigIntegerField()


if db.is_closed():
    db.connect()
    db.create_tables([Post, SubscriptionState])
