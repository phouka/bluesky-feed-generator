from datetime import datetime

import peewee

db = peewee.SqliteDatabase('feed_database.db')
watch_lookup = {}
watch_list = {}

ignore_lookup = {}
ignore_list = {}

class BaseModel(peewee.Model):
    class Meta:
        database = db


class Repost(BaseModel):
    uri = peewee.CharField(index=True)
    via_uri = peewee.CharField()
    orig_uri = peewee.CharField()
    cid = peewee.CharField()
    indexed_at = peewee.DateTimeField(default=datetime.utcnow)


class User(BaseModel):
    did = peewee.CharField(index=True)
    is_follower = peewee.BooleanField(default=False)
    # number of times seen self
    exposure = peewee.IntegerField(default=0)
    # number of times interacted (just reposts)
    engagement = peewee.IntegerField(default=0)
    # number of followers not following self
    unique_followers = peewee.IntegerField(default=0)
    # number of times followers-that-are-not-following-self have seen self
    #follower_exposure = peewee.IntegerField(default=0)
    # number of times followers-that-are-not-following-self have engaged with self
    #follower_engagement = peewee.IntegerField(default=0)
    # likelihood of engaging with self posts
    chance_to_engage = peewee.FloatField(default=0.0)
    indexed_at = peewee.DateTimeField(default=datetime.utcnow)

# this keeps track of where in the firehose the events were last read
# this allows the system to catch up to the stream after a restart
class SubscriptionState(BaseModel):
    service = peewee.CharField(unique=True)
    cursor = peewee.BigIntegerField()


if db.is_closed():
    db.connect()
    db.create_tables([Repost, User, SubscriptionState])
