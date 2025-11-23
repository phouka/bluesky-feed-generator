
from server.database import User, Engagement, ENGAGEMENT_LIKE, ENGAGEMENT_REPOST
from server.database import AggStat, AGG_FOLLOWER, AGG_LIKE, AGG_REPOST
from server.database import watch_lookup, watch_list, ignore_lookup, ignore_list
from atproto_identity.resolver import IdResolver
from server.client import client
from server.logger import logger
from atproto import models
from server import config

import time
from datetime import datetime, timezone, timedelta

def get_list_contents(list_uri: str) -> dict:
    users = []
    cursor = None
    while True:
        new_list = client.app.bsky.graph.get_list(models.AppBskyGraphGetList.Params(list=list_uri, cursor=cursor, limit=100))
        for item in new_list.items:
            users.append(item)
        if new_list.cursor is None:
            break
        time.sleep(0.1)
        cursor = new_list.cursor
    return users

def get_follow_contents(did_to_follow: str) -> dict:
    users = []
    cursor = None
    while True:
        new_list = client.get_followers(actor=did_to_follow, cursor=cursor, limit=100)
        for item in new_list.followers:
            users.append(item)
        if new_list.cursor is None:
            break
        time.sleep(0.1)
        cursor = new_list.cursor
    return users


def get_follow_uri(follower_did: str, did_to_follow: str) -> dict:
    resolved = IdResolver().did.resolve(follower_did)
    new_url = resolved.service[0].service_endpoint
    client.update_base_url(new_url)

    try:
        cursor = None
        while True:
            new_list = client.app.bsky.graph.follow.list(repo=follower_did, cursor=cursor, limit=100)
            for k, item in new_list.records.items():
                if item.subject == did_to_follow:
                    return k
            if new_list.cursor is None:
                break
            time.sleep(0.1)
            cursor = new_list.cursor
    except Exception as e:
        logger.error(f'Error getting follow URI for {follower_did} -> {did_to_follow}: {e}')
    return None



def setup():

    """
    created_list_item = client.app.bsky.graph.listitem.create(
        list_owner,
        models.AppBskyGraphListitem.Record(
            list=shares_uncategorized,
            subject=user,
            created_at=client.get_current_time_iso(),
        ),
    )
    deleted_list_item = client.app.bsky.graph.listitem.delete(
        list_owner,
        AtUri.from_str(user).rkey,
    )
    """


    # tables:
    # engagement event: type(like/repost), uri, target uri, create/delete, timestamp; last hour of self-targeted events are counted and taken every hour.  records older than 1 month purged
    # agg_stat: stat(followers/likes/reposts), amount, timestamp; taken every hour for self.  used to track followers, likes, share frequency

    # clear all is_follower from users who have them
    User.update({User.follow_id:''}).where(User.follow_id != '').execute()

    # read all followers and update the users table
    did_to_follow = config.get_self()
    followers = get_follow_contents(did_to_follow)
    for follower in followers:
        # TODO: this is very inefficient, optimize later
        #follow_uri = get_follow_uri(follower.did, did_to_follow)
        # TODO: by setting this value to temp, delete events won't work
        follow_uri = "temp"
        if follow_uri is not None:
            User.get_or_create(did=follower.did, defaults={'did': follower.did})
            User.update({User.follow_id:follow_uri}).where(User.did == follower.did).execute()


    # from target users in Similar-Audience list, get all posts and add to total_similar_posts
    # for each post in total_similar_posts, get shares and add sharing_account to total_exposed_Accounts if not already exists
    # when the followed user is a repost, add reposting account to final_table with default values
    # this does not include the target user's own reposts

    # iter 0: do not prioritize, just show all shares of these peoples' posts
    # iter 1: filter out the people that follow self

    # iter 2: filter out the people with crowded notifs: over 100 like/share events last 24 hours

    # iter 3: prioritize based on if they've been exposed to you, and if they've engaged

    # iter 4: (ML) based on follows, find chance of following self, and rank people with high chances
    # iter 5: (ML) based on engagements, find chance of engaging with self, and rank people with high chances
    watch_lookup.clear()
    watch_list.clear()
    for user_list in config.FOLLOW_LIST:
        list_items = get_list_contents(user_list)
        for item in list_items:
            watch_lookup[item.uri] = item.subject.did
            watch_list[item.subject.did] = True

    # create the ignore list
    ignore_lookup.clear()
    ignore_list.clear()
    for user_list in config.IGNORE_LIST:
        list_items = get_list_contents(user_list)
        for item in list_items:
            ignore_lookup[item.uri] = item.subject.did
            ignore_list[item.subject.did] = True


def update_periodic():

    while True:
        last_time = datetime.now(timezone.utc)

        seconds_to_next_hour = 3600 - (last_time.minute * 60 + last_time.second + last_time.microsecond / 1_000_000)
        if seconds_to_next_hour > 0:
            time.sleep(seconds_to_next_hour)

        cur_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        prev_day = cur_day - timedelta(days=1)

        # get follow count
        did_to_follow = config.get_self()
        followers = get_follow_contents(did_to_follow)
        follow_count = len(followers)
        AggStat.create(
            event_type=AGG_FOLLOWER,
            time=cur_day,
            amount=follow_count
        )
        
        like_count = Engagement.select().where(
                (Engagement.event_type == ENGAGEMENT_LIKE) &
                (Engagement.created_at < cur_day) &
                (Engagement.created_at >= prev_day)).count()
        AggStat.create(
            event_type=AGG_LIKE,
            time=cur_day,
            amount=like_count
        )

        repost_count = Engagement.select().where(
                (Engagement.event_type == ENGAGEMENT_REPOST) &
                (Engagement.created_at < cur_day) &
                (Engagement.created_at >= prev_day)).count()
        AggStat.create(
            event_type=AGG_REPOST,
            time=cur_day,
            amount=repost_count
        )
        
