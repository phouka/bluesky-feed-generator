import os
import logging

from dotenv import load_dotenv

from server.logger import logger

load_dotenv()

HANDLE = os.environ.get('HANDLE')
APP_PASS = os.environ.get('PASSWORD')

SERVICE_DID = os.environ.get('SERVICE_DID')
HOSTNAME = os.environ.get('APP_HOSTNAME')
FLASK_RUN_FROM_CLI = os.environ.get('FLASK_RUN_FROM_CLI')

if FLASK_RUN_FROM_CLI:
    logger.setLevel(logging.DEBUG)

if not HOSTNAME:
    raise RuntimeError('You should set "APP_HOSTNAME" environment variable first.')

if not SERVICE_DID:
    SERVICE_DID = f'did:web:{HOSTNAME}'


FEED_URI = os.environ.get('FEED_URI')
if not FEED_URI:
    raise RuntimeError('Publish your feed first (run publish_feed.py) to obtain Feed URI. '
                       'Set this URI to "FEED_URI" environment variable.')

USER_LIST = os.environ.get('USER_LIST', '').split(',')

FOLLOW_LIST = os.environ.get('FOLLOW_LIST', '').split(',')

IGNORE_LIST = os.environ.get('IGNORE_LIST', '').split(',')

DB_NAME = os.environ.get('DB_NAME')
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = int(os.environ.get('DB_PORT'))
DB_USER = os.environ.get('DB_USER')
DB_PASS = os.environ.get('DB_PASS')

def _get_bool_env_var(value: str) -> bool:
    if value is None:
        return False

    normalized_value = value.strip().lower()
    if normalized_value in {'1', 'true', 't', 'yes', 'y'}:
        return True

    return False

DISABLE_JOBS = _get_bool_env_var(os.environ.get('DISABLE_JOBS'))
DEBUG_FEED = _get_bool_env_var(os.environ.get('DEBUG_FEED'))

IGNORE_ARCHIVED_POSTS = _get_bool_env_var(os.environ.get('IGNORE_ARCHIVED_POSTS'))
IGNORE_REPLY_POSTS = _get_bool_env_var(os.environ.get('IGNORE_REPLY_POSTS'))

def get_self() -> str:
    return FOLLOW_LIST[0].split('/')[2]