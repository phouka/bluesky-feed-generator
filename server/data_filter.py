import datetime

from collections import defaultdict

from atproto import models

from server import config
from server.logger import logger
from server.database import db, Repost, watch_lookup, watch_list, ignore_lookup, ignore_list
from server.client import client


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


def should_ignore_post(created_post: dict) -> bool:
    author = created_post['author']
    record = created_post['record']
    uri = created_post['uri']

    if config.IGNORE_ARCHIVED_POSTS and is_archive_post(record):
        logger.debug(f'Ignoring archived post: {uri}')
        return True

    if config.IGNORE_REPLY_POSTS and record.reply:
        logger.debug(f'Ignoring reply post: {uri}')
        return True

    # check against reposter in ignore list, filter out if in list
    if author in ignore_list:
        logger.debug(f'Ignoring repost from ignored reposter: {uri}')
        return True

    # check subject against author in list, and filter out if in list
    orig_uri = record.subject.uri
    url_parts = orig_uri.split('/')
    orig_author = url_parts[2]
    post_rkey = url_parts[-1]

    if orig_author not in watch_list:
        logger.debug(f'Ignoring repost of post from unlisted author: {uri}')
        return True

    # TODO: check against post author in is_follower


    # retrieve the original post and check if it has media attachments
    orig_record = client.get_post(post_rkey, orig_author).value
    post_with_images = isinstance(orig_record.embed, models.AppBskyEmbedImages.Main)
    post_with_video = isinstance(orig_record.embed, models.AppBskyEmbedVideo.Main)

    if not post_with_images and not post_with_video:
         logger.debug(f'Ignoring non-media post: {uri}')
         return True

    inlined_text = orig_record.text.replace('\n', ' ')

    # print all texts just as demo that data stream works
    logger.debug(
        f'NEW POST '
        f'[CREATED_AT={orig_record.created_at}]'
        f'[AUTHOR={author}]'
        f': {inlined_text}'
    )

    return False


def operations_callback(ops: defaultdict) -> None:
    for created_post in ops[models.ids.AppBskyGraphListitem]['created']:
        # add to local list if the item is from the target list
        record_list = created_post['record'].list
        list_item = created_post['uri']
        for user_list in config.FOLLOW_LIST:
            if record_list == user_list:
                watch_list[list_item] = True
        for user_list in config.IGNORE_LIST:
            if record_list == user_list:
                ignore_list[list_item] = True

    for post in ops[models.ids.AppBskyGraphListitem]['deleted']:
        # remove from local list if the item is from the target list
        list_uri = post['uri']
        if list_uri in watch_lookup:
            list_item = watch_lookup[list_uri]
            del watch_lookup[list_uri]
            del watch_list[list_item]
        
        if list_uri in ignore_lookup:
            list_item = ignore_lookup[list_uri]
            del ignore_lookup[list_uri]
            del ignore_list[list_item]

    for created_post in ops[models.ids.AppBskyGraphFollow]['created']:
        # TODO: update database to mark user as is_follower
        pass

    for created_post in ops[models.ids.AppBskyGraphFollow]['deleted']:
        # TODO: update database to mark user is_follower to False
        pass


    posts_to_create = []
    for created_post in ops[models.ids.AppBskyFeedRepost]['created']:
        record = created_post['record']

        if should_ignore_post(created_post):
            continue

        try:
            via_uri = record.via.uri
        except AttributeError as e:
            via_uri = ""
        
        orig_uri = record.subject.uri
        # the primary key should be the original post id
        # if a new repost appears, do not update
        post_dict = {
            'uri': created_post['uri'],
            'via_uri': via_uri,
            'orig_uri': orig_uri,
            'cid': created_post['cid'],
        }
        posts_to_create.append(post_dict)

    #posts_to_delete = ops[models.ids.AppBskyFeedRepost]['deleted']
    #if posts_to_delete:
    #    post_uris_to_delete = [post['uri'] for post in posts_to_delete]
    #    Post.delete().where(Post.uri.in_(post_uris_to_delete))
    #    logger.debug(f'Deleted from feed: {len(post_uris_to_delete)}')

    if posts_to_create:
        with db.atomic():
            for post_dict in posts_to_create:
                Repost.create(**post_dict)
        logger.debug(f'Added to feed: {len(posts_to_create)}')
