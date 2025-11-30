
from server.database import watch_lookup, watch_list, ignore_lookup, ignore_list, Post
from server.client import client
from server.logger import logger
from atproto import models
from server import config

from server.database_sqlite import Post as Post_sqlite, SubscriptionState as SubscriptionState_sqlite
from server.database import Post, SubscriptionState

import time

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


    posts = Post_sqlite.select()
    for post in posts:
        Post.create(
            orig_uri=post.orig_uri,
            uri=post.uri,
            cid=post.cid,
            indexed_at=post.indexed_at,
        )

    subs = SubscriptionState_sqlite.select()
    for sub in subs:
        SubscriptionState.create(
            service=sub.service,
            cursor=sub.cursor,
        )

    # create the author share watch list
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

