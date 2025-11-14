from datetime import datetime
from typing import Optional

from server import config
from server.database import Repost, watch_list, ignore_list

uri = config.FEED_URI
CURSOR_EOF = 'eof'

def compute_cursor(posts) -> str:
    if not posts:
        return CURSOR_EOF
    last_post = posts[-1]
    return f'{int(last_post.indexed_at.timestamp() * 1000)}::{last_post.cid}'

def handler(cursor: Optional[str], limit: int) -> dict:

    feed_posts = []
    while True:
        posts = Repost.select().order_by(Repost.cid.desc()).order_by(Repost.indexed_at.desc()).limit(limit)
        if cursor:
            if cursor == CURSOR_EOF:
                break
            cursor_parts = cursor.split('::')
            if len(cursor_parts) != 2:
                raise ValueError('Malformed cursor')

            indexed_at, cid = cursor_parts
            indexed_at = datetime.fromtimestamp(int(indexed_at) / 1000)
            posts = posts.where(((Repost.indexed_at == indexed_at) & (Repost.cid < cid)) | (Repost.indexed_at < indexed_at))

        
        for post in posts:
            url_parts = post.uri.split('/')
            author = url_parts[2]

            if author in ignore_list:
                continue
            
            orig_url_parts = post.orig_uri.split('/')
            orig_author = orig_url_parts[2]

            if orig_author not in watch_list:
                continue

            feed_posts.append(post)
            if len(feed_posts) >= limit:
                break

        if len(feed_posts) >= limit:
            break

        cursor = compute_cursor(posts)

    next_cursor = compute_cursor(feed_posts)

    feed = []
    for post in feed_posts:
        feed.append({'post': post.orig_uri, "reason": { "$type": "app.bsky.feed.defs#skeletonReasonRepost", "repost": post.uri } })

    return {
        'cursor': next_cursor,
        'feed': feed
    }
