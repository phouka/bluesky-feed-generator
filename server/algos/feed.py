from datetime import datetime
from typing import Optional

from server import config
from server.database import Post, watch_list, ignore_list

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
        posts = Post.select().order_by(Post.cid.desc()).order_by(Post.indexed_at.desc()).limit(limit)
        if cursor:
            if cursor == CURSOR_EOF:
                break
            cursor_parts = cursor.split('::')
            if len(cursor_parts) != 2:
                raise ValueError('Malformed cursor')

            indexed_at, cid = cursor_parts
            indexed_at = datetime.fromtimestamp(int(indexed_at) / 1000)
            posts = posts.where(((Post.indexed_at == indexed_at) & (Post.cid < cid)) | (Post.indexed_at < indexed_at))

        
        for post in posts:
            author = post.uri.split('/')[2]
            orig_author = post.orig_uri.split('/')[2]

            if orig_author in watch_list:
                continue
            
            if orig_author in ignore_list:
                continue
            
            if author in ignore_list:
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
