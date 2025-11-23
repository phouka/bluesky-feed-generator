import datetime

from collections import defaultdict

from atproto import models

from server import config
from server.logger import logger
from server.database import db, Repost, User, Engagement, MainPost, Exposure
from server.database import watch_lookup, watch_list, ignore_lookup, ignore_list
from server.database import OP_CREATE, OP_DELETE, ENGAGEMENT_LIKE, ENGAGEMENT_REPOST
from server.client import client

from server.alike_setup import get_follow_contents

def extract_author(uri: str) -> str:
    url_parts = uri.split('/')
    author = url_parts[2]
    return author

def is_archive_post(record: 'models.AppBskyFeedPost.Record') -> bool:
    # Sometimes users will import old posts from Twitter/X which con flood a feed with
    # old posts. Unfortunately, the only way to test for this is to look an old
    # created_at date. However, there are other reasons why a post might have an old
    # date, such as firehose or firehose consumer outages. It is up to you, the feed
    # creator to weigh the pros and cons, amd and optionally include this function in
    # your filter conditions, and adjust the threshold to your liking.
    #
    # See https://github.com/MarshalX/bluesky-feed-generator/pull/21

    archived_threshold = datetime.timedelta(days=7)
    created_at = datetime.datetime.fromisoformat(record.created_at)
    now = datetime.datetime.now(datetime.UTC)

    return now - created_at > archived_threshold


def should_add_target_repost(created_post: dict) -> bool:
    author = created_post['author']
    record = created_post['record']
    uri = created_post['uri']

    if config.IGNORE_ARCHIVED_POSTS and is_archive_post(record):
        logger.debug(f'Ignoring archived post: {uri}')
        return False

    if config.IGNORE_REPLY_POSTS and record.reply:
        logger.debug(f'Ignoring reply post: {uri}')
        return False

    # check against reposter in ignore list, filter out if in list
    if author in ignore_list:
        logger.debug(f'Ignoring repost from ignored reposter: {uri}')
        return False

    # check subject against author in list, and filter out if not in list
    orig_uri = record.subject.uri
    url_parts = orig_uri.split('/')
    orig_author = url_parts[2]
    post_rkey = url_parts[-1]

    if orig_author not in watch_list:
        logger.debug(f'Ignoring repost of post from unlisted author: {uri}')
        return False

    # check against post author is follower
    follower = User.get_or_none((User.did == author) & (User.follow_id != ''))
    if follower is not None:
        logger.debug(f'Ignoring repost from follower: {uri}')
        return False


    # retrieve the original post and check if it has media attachments
    orig_record = client.get_post(post_rkey, orig_author).value
    post_with_images = isinstance(orig_record.embed, models.AppBskyEmbedImages.Main)
    post_with_video = isinstance(orig_record.embed, models.AppBskyEmbedVideo.Main)

    if not post_with_images and not post_with_video:
         logger.debug(f'Ignoring non-media post: {uri}')
         return False

    inlined_text = orig_record.text.replace('\n', ' ')

    # print all texts just as demo that data stream works
    logger.debug(
        f'NEW POST '
        f'[CREATED_AT={orig_record.created_at}]'
        f'[AUTHOR={author}]'
        f': {inlined_text}'
    )

    return True


def should_add_self_post(created_event: dict) -> bool:

    record = created_event['record']
    author = created_event['author']

    if config.IGNORE_ARCHIVED_POSTS and is_archive_post(record):
        logger.debug(f'Ignoring archived post: {uri}')
        return False

    if config.IGNORE_REPLY_POSTS and record.reply:
        logger.debug(f'Ignoring reply post: {uri}')
        return False
    
    if author == config.get_self():
        return True
    
    return False

def should_add_self_stat(created_event: dict) -> bool:

    record = created_event['record']
    uri = created_event['uri']

    if config.IGNORE_ARCHIVED_POSTS and is_archive_post(record):
        logger.debug(f'Ignoring archived post: {uri}')
        return False

    if config.IGNORE_REPLY_POSTS and record.reply:
        logger.debug(f'Ignoring reply post: {uri}')
        return False
    
    orig_uri = record.subject.uri
    orig_author = extract_author(orig_uri)

    if orig_author == config.get_self():
        return True
    
    return False

def should_add_busy_notif(created_event: dict) -> bool:

    record = created_event['record']

    orig_uri = record.subject.uri
    orig_author = extract_author(orig_uri)

    # TODO: non-follower needs it to track notification busyness
    # user = User.get_or_none(User.did == orig_author)
    # if user is not None:
    #     if user.follow_id == '':
    #         return True

    return False

def operations_callback(ops: defaultdict) -> None:
    for op_event in ops[models.ids.AppBskyGraphListitem]['created']:
        # add to local list if the item is from the target list
        record_list = op_event['record'].list
        list_item = op_event['uri']
        for user_list in config.FOLLOW_LIST:
            if record_list == user_list:
                watch_list[list_item] = True
        for user_list in config.IGNORE_LIST:
            if record_list == user_list:
                ignore_list[list_item] = True

    for op_event in ops[models.ids.AppBskyGraphListitem]['deleted']:
        # remove from local list if the item is from the target list
        list_uri = op_event['uri']
        if list_uri in watch_lookup:
            list_item = watch_lookup[list_uri]
            del watch_lookup[list_uri]
            del watch_list[list_item]
        
        if list_uri in ignore_lookup:
            list_item = ignore_lookup[list_uri]
            del ignore_lookup[list_uri]
            del ignore_list[list_item]

    # Self Follows
    # when follow to self is created, update the user table to reflect it
    self_follows_created = []
    for op_event in ops[models.ids.AppBskyGraphFollow]['created']:
        # update database to mark user as is_follower
        uri = op_event['uri']
        follower = extract_author(uri)

        record = op_event['record']
        follow_target = record.subject
        req_follow_target = config.get_self()
        if follow_target != req_follow_target:
            continue
        follow_dict = {
            'did': follower,
            'uri': uri,
        }
        self_follows_created.append(follow_dict)

    if self_follows_created:
        with db.atomic():
            for follow_dict in self_follows_created:
                follower = follow_dict['did']
                uri = follow_dict['uri']
                User.get_or_create(did=follower, defaults={'did': follower})
                User.update({User.follow_id:uri}).where(User.did == follower).execute()

    self_follows_deleted = ops[models.ids.AppBskyGraphFollow]['deleted']
    if self_follows_deleted:
        follow_uris_to_delete = [post['uri'] for post in self_follows_deleted]
        # update database to mark user is_follower to False
        User.update({User.follow_id:''}).where(User.follow_id.in_(follow_uris_to_delete)).execute()
        logger.debug(f'Deleted from follows: {len(follow_uris_to_delete)}')

    # self stat
    # on like/share on self, log an event
    self_stat_created = []

    # TODO:
    # Notif Busyness
    # need a log of all like/share/follow events with timestamps, targeted at self and logged users
    # when share/like, check if user is in list and is not follower.  add event if so
    # TODO:
    # phase out after 72 hours
    for op_event in ops[models.ids.AppBskyFeedLike]['created']:
        record = op_event['record']

        try:
            via_uri = record.via.uri
        except AttributeError as e:
            via_uri = ""

        if should_add_self_stat(op_event):
            
            event_dict = {
                'uri': op_event['uri'],
                'author': extract_author(op_event['uri']),
                'event_type': ENGAGEMENT_LIKE,
                'create_delete': OP_CREATE,
                'via_uri': via_uri,
                'orig_uri': record.subject.uri,
                'orig_author': extract_author(record.subject.uri),
                'created_at': datetime.datetime.strptime(record.created_at, '%Y-%m-%dT%H:%M:%S.%fZ'),
                'cid': op_event['cid'],
            }
            self_stat_created.append(event_dict)


    # TODO:
    # Self Engagement
    # when self posts, get followers at time of post and add follower to users table with exposure + 1
    # when self is shared, add sharer to users with engagement +1 and, if not follower, exposure +1
    # + get followers of sharer DURING TIME OF SHARE and add (follower, increment 1) to total_exposed_accounts
    for op_event in ops[models.ids.AppBskyFeedPost]['created']:
        record = op_event['record']

        if not should_add_self_post(op_event):
            continue

        MainPost.create(
            uri=op_event['uri'],
            cid=op_event['cid'],
            created_at=datetime.datetime.strptime(record.created_at, '%Y-%m-%dT%H:%M:%S.%fZ'),
        )
        # get all followers at time of post
        followers = User.select().where(User.follow_id != '')
        with db.atomic():
            total = 0
            for follower in followers:
                Exposure.create(uri=op_event['uri'], seen_by=follower.did)
                total += 1
            logger.debug(f'Added to exposure: {len(total)}')


    # Target Reposts
    # when someone reposts, check if repost target is followed
    # if so, check if reposter is follower
    # if not, add repost to list
    # also, add the reposter to the users table
    target_reposts_created = []
    for op_event in ops[models.ids.AppBskyFeedRepost]['created']:
        record = op_event['record']

        try:
            via_uri = record.via.uri
        except AttributeError as e:
            via_uri = ""

        if should_add_target_repost(op_event):

            orig_uri = record.subject.uri
            # the primary key should be the original post id
            # if a new repost appears, do not update
            post_dict = {
                'uri': op_event['uri'],
                'via_uri': via_uri,
                'orig_uri': orig_uri,
                'cid': op_event['cid'],
                'created_at': datetime.datetime.strptime(record.created_at, '%Y-%m-%dT%H:%M:%S.%fZ'),
            }
            target_reposts_created.append(post_dict)
        

        if should_add_self_stat(op_event):
            
            event_dict = {
                'uri': op_event['uri'],
                'author': extract_author(op_event['uri']),
                'event_type': ENGAGEMENT_REPOST,
                'create_delete': OP_CREATE,
                'via_uri': via_uri,
                'orig_uri': record.subject.uri,
                'orig_author': extract_author(record.subject.uri),
                'cid': op_event['cid'],
                'created_at': datetime.datetime.strptime(record.created_at, '%Y-%m-%dT%H:%M:%S.%fZ'),
            }
            self_stat_created.append(event_dict)

    if target_reposts_created:
        with db.atomic():
            for post_dict in target_reposts_created:
                Repost.create(**post_dict)
                author = extract_author(post_dict['uri'])
                User.create(did=author)
        logger.debug(f'Added to feed: {len(target_reposts_created)}')

    #posts_to_delete = ops[models.ids.AppBskyFeedRepost]['deleted']
    #if posts_to_delete:
    #    post_uris_to_delete = [post['uri'] for post in posts_to_delete]
    #    Post.delete().where(Post.uri.in_(post_uris_to_delete))
    #    logger.debug(f'Deleted from feed: {len(post_uris_to_delete)}')

    if self_stat_created:
        with db.atomic():
            for event_dict in self_stat_created:
                Engagement.create(**event_dict)
        logger.debug(f'Added to engagements: {len(self_stat_created)}')

        # get all followers at time of post
        for event_dict in self_stat_created:
            if event_dict['event_type'] == ENGAGEMENT_REPOST:
                followers = get_follow_contents(event_dict['author'])
                with db.atomic():
                    for follower in followers:
                        Exposure.create(uri=event_dict['uri'], seen_by=follower.did)

