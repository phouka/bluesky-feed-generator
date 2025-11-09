import datetime

from collections import defaultdict

from atproto import models

from server import config
from server.logger import logger
from server.database import db, Post, watch_list
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
        # logger.debug(f'Ignoring reply post: {uri}')
        return True

    # check against author in list, filter out if not in list
    if author not in watch_list:
        # logger.debug(f'Ignoring repost from unlisted author: {uri}')
        return True

    # check subject against author in list, and filter out if in list
    orig_uri = record.subject.uri
    url_parts = orig_uri.split('/')
    orig_author = url_parts[2]
    post_rkey = url_parts[-1]

    if orig_author in watch_list:
        logger.debug(f'Ignoring repost of post from listed author: {uri}')
        return True

    # check if we already have this original post in the database
    try:
        existing_post = Post.get(Post.orig_uri == orig_uri)
    except Post.DoesNotExist:
        existing_post = None

    if existing_post:
        logger.debug(f'Ignoring repost of already existing post: {uri}')
        return True

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
        if record_list == config.LIST_NAME:
            watch_list[list_item] = True

    for post in ops[models.ids.AppBskyGraphListitem]['deleted']:
        # remove from local list if the item is from the target list
        list_item = post['uri']
        if list_item in watch_list:
            del watch_list[list_item]


    posts_to_create = []
    for created_post in ops[models.ids.AppBskyFeedRepost]['created']:
        record = created_post['record']
        orig_uri = record.subject.uri

        if should_ignore_post(created_post):
            continue

        # the primary key should be the original post id
        # if a new repost appears, do not update
        post_dict = {
            'orig_uri': orig_uri,
            'uri': created_post['uri'],
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
                Post.create(**post_dict)
        logger.debug(f'Added to feed: {len(posts_to_create)}')
