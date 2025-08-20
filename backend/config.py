
import os

# スプレッドシートIDとアイキャッチディレクトリの設定
HOLOLIVE_EYECATCH_DIR = "eyecatch"
NIJISANJI_EYECATCH_DIR = "eyecatch2"
HOLOLIVE_EN_EYECATCH_DIR = "eyecatch3"

# 環境変数から取得（なければダミー値）
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID", "dummy_id")

# ホロライブのTwitter APIの設定
HOLOLIVE_client_id = os.environ.get('HOLOLIVE_client_id', 'dummy')
HOLOLIVE_client_secret = os.environ.get('HOLOLIVE_client_secret', 'dummy')
HOLOLIVE_api_key = os.environ.get('HOLOLIVE_api_key', 'dummy')
HOLOLIVE_api_secret = os.environ.get('HOLOLIVE_api_secret', 'dummy')
HOLOLIVE_access_token = os.environ.get('HOLOLIVE_access_token', 'dummy')
HOLOLIVE_access_token_secret = os.environ.get('HOLOLIVE_access_token_secret', 'dummy')
HOLOLIVE_Bearer_token = os.environ.get('HOLOLIVE_Bearer_token', 'dummy')

# にじさんじのTwitter API設定
NIJISANJI_api_key = os.environ.get('NIJISANJI_api_key', 'dummy')
NIJISANJI_api_secret = os.environ.get('NIJISANJI_api_secret', 'dummy')
NIJISANJI_access_token = os.environ.get('NIJISANJI_access_token', 'dummy')
NIJISANJI_access_token_secret = os.environ.get('NIJISANJI_access_token_secret', 'dummy')
