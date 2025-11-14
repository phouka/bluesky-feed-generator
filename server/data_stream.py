import logging
from collections import defaultdict

from atproto import AtUri, CAR, firehose_models, FirehoseSubscribeReposClient, models, parse_subscribe_repos_message
from atproto.exceptions import FirehoseError

from server import config
from server.database import SubscriptionState
from server.logger import logger
from server.database import watch_lookup, watch_list, ignore_lookup, ignore_list
from server.client import client

_INTERESTED_RECORDS = {
    models.AppBskyFeedRepost: models.ids.AppBskyFeedRepost,
    models.AppBskyGraphListitem: models.ids.AppBskyGraphListitem,
    models.AppBskyGraphFollow: models.ids.AppBskyGraphFollow,
}


def _get_ops_by_type(commit: models.ComAtprotoSyncSubscribeRepos.Commit) -> defaultdict:
    operation_by_type = defaultdict(lambda: {'created': [], 'deleted': []})

    car = CAR.from_bytes(commit.blocks)
    for op in commit.ops:
        if op.action == 'update':
            # we are not interested in updates
            continue

        uri = AtUri.from_str(f'at://{commit.repo}/{op.path}')

        if op.action == 'create':
            if not op.cid:
                continue

            create_info = {'uri': str(uri), 'cid': str(op.cid), 'author': commit.repo}

            record_raw_data = car.blocks.get(op.cid)
            if not record_raw_data:
                continue

            record = models.get_or_create(record_raw_data, strict=False)
            if record is None:  # unknown record (out of bsky lexicon)
                continue

            for record_type, record_nsid in _INTERESTED_RECORDS.items():
                if uri.collection == record_nsid and models.is_record_type(record, record_type):
                    operation_by_type[record_nsid]['created'].append({'record': record, **create_info})
                    break

        if op.action == 'delete':
            for record_type, record_nsid in _INTERESTED_RECORDS.items():
                if uri.collection == record_nsid:
                    operation_by_type[record_nsid]['deleted'].append({'uri': str(uri)})

    return operation_by_type


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

from atproto_identity.resolver import IdResolver

def run(name, operations_callback, stream_stop_event=None):
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

    # from Self get all posts to add to total_oc_posts
    # for each post in total_oc_posts, get followers at the time of post and add (follower, increment 1) to total_exposed_accounts
    # for each post in total_oc_posts, get shares and add (sharer, share) to total_sharing_accounts
    # for each (account, share) in total_sharing_accounts, get followers DURING THE SHARE and add (follower, increment 1) to total_exposed_accounts
    # total_exposed_accounts is the set of all accounts that have seen self

    # when post, get followers at time of post and add (follower, increment 1) to total_exposed_accounts
    # when share, add (sharing account, share) to total_sharing_accounts + add (sharing account, increment 1) to total_engaged_Accounts
    # + get followers DURING TIME OF SHARE and add (follower, increment 1) to total_exposed_accounts

    # TODO:
    # clear all is_follower from users who have them
    # read all followers and update the users table

    # from target users in Similar-Audience list, get all posts and add to total_similar_posts
    # for each post in total_similar_posts, get shares and add sharing_account to total_exposed_Accounts if not already exists
    # when the followed user is a repost, add reposting account to final_table with default values
    # this does not include the target user's own reposts

    # iter 0: do not prioritize, just show all shares of these peoples' posts
    # iter 1: filter out the people that follow self
    # iter 1: based on follows, find chance of following self, and prioritize the shares from people with high chances
    # iter 2: based on engagements, find chance of engaging with self, and prioritize the shares from people with high chances
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
    
    while stream_stop_event is None or not stream_stop_event.is_set():
        try:
            _run(name, operations_callback, stream_stop_event)
        except FirehoseError as e:
            if logger.level == logging.DEBUG:
                raise e
            logger.error(f'Firehose error: {e}. Reconnecting to the firehose.')


def _run(name, operations_callback, stream_stop_event=None):
    state = SubscriptionState.get_or_none(SubscriptionState.service == name)

    params = None
    if state:
        params = models.ComAtprotoSyncSubscribeRepos.Params(cursor=state.cursor)

    client = FirehoseSubscribeReposClient(params)

    if not state:
        SubscriptionState.create(service=name, cursor=0)

    def on_message_handler(message: firehose_models.MessageFrame) -> None:
        # stop on next message if requested
        if stream_stop_event and stream_stop_event.is_set():
            client.stop()
            return

        commit = parse_subscribe_repos_message(message)
        if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
            return

        # update stored state every ~1k events
        if commit.seq % 1000 == 0:  # lower value could lead to performance issues
            logger.debug(f'Updated cursor for {name} to {commit.seq}')
            client.update_params(models.ComAtprotoSyncSubscribeRepos.Params(cursor=commit.seq))
            SubscriptionState.update(cursor=commit.seq).where(SubscriptionState.service == name).execute()

        if not commit.blocks:
            return

        operations_callback(_get_ops_by_type(commit))

    client.start(on_message_handler)
