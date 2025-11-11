from datetime import datetime

import peewee

db = peewee.SqliteDatabase('feed_database.db')
watch_list = {}
ignore_list = {}

class BaseModel(peewee.Model):
    class Meta:
        database = db


class Post(BaseModel):
    orig_uri = peewee.CharField(index=True)
    uri = peewee.CharField()
    cid = peewee.CharField()
    indexed_at = peewee.DateTimeField(default=datetime.utcnow)

# this keeps track of where in the firehose the events were last read
# this allows the system to catch up to the stream after a restart
class SubscriptionState(BaseModel):
    service = peewee.CharField(unique=True)
    cursor = peewee.BigIntegerField()


if db.is_closed():
    db.connect()
    db.create_tables([Post, SubscriptionState])
