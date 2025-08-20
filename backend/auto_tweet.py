
import gspread
import os
import config
import tweepy
import json
from datetime import datetime, timedelta, timezone
from utility import extract_video_id, sanitize_filename, format_time
from youtube_handler import get_video_metadata


# --- Twitter投稿関数 ---
def schedule_tweet_for_video(group_id, tweet_text):
    """
    group_id: "hololive" or "nijisanji"
    tweet_text: 投稿するテキスト
    """
    if group_id == "hololive":
        api_key = config.HOLOLIVE_api_key
        api_secret = config.HOLOLIVE_api_secret
        access_token = config.HOLOLIVE_access_token
        access_token_secret = config.HOLOLIVE_access_token_secret
    elif group_id == "nijisanji":
        api_key = config.NIJISANJI_api_key
        api_secret = config.NIJISANJI_api_secret
        access_token = config.NIJISANJI_access_token
        access_token_secret = config.NIJISANJI_access_token_secret
    else:
        raise ValueError("Unknown group_id")

    # Tweepy v4.x OAuth1.0a認証
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
    api = tweepy.API(auth)
    # 即時投稿（予約投稿は有料APIのみ）
    api.update_status(status=tweet_text)
    print(f"✓ Twitter投稿完了: {tweet_text[:40]}...")


def main():
    # 1. 現在時刻が当日の18時(JST)を過ぎて30分以内か判定
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    today_18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now < today_18:
        print("18時前なので処理終了")
        return
    if now > today_18 + timedelta(minutes=30):
        print("18時30分を過ぎているので処理終了")
        return

    # 2. summary_videos.jsonを読み込む
    json_path = os.path.join(os.path.dirname(__file__), "data", "summary_videos.json")
    if not os.path.exists(json_path):
        print("summary_videos.jsonが存在しません")
        return
    with open(json_path, encoding="utf-8") as f:
        videos = json.load(f)

    # 3. 各動画のscheduled_publish_time(UTC)を参照し、当日の日本時間18時が存在するか判定
    found = False
    for video in videos.values():
        if isinstance(video, str):
            try:
                video = json.loads(video)
            except Exception:
                # 文字列がvideo_id等ならスキップ
                print(f"動画情報として無視: {video}")
                continue
        if not isinstance(video, dict):
            print(f"動画情報がdict型でないのでスキップ: {video}")
            continue
        sched_utc = video.get("scheduled_publish_time")
        if not sched_utc:
            continue
        # scheduled_publish_timeはISO8601想定
        try:
            sched_dt_utc = datetime.fromisoformat(sched_utc.replace("Z", "+00:00"))
        except Exception:
            continue
        sched_dt_jst = sched_dt_utc.astimezone(JST)
        # 当日18時ちょうど
        if (sched_dt_jst.date() == now.date() and sched_dt_jst.hour == 18 and sched_dt_jst.minute == 0):
            found = True
            # 4. group_id, channel, video_id, upload_url取得

            group_name = video.get("group_name", "")
            if group_name == "ホロライブ":
                group_id = "hololive"
            elif group_name == "にじさんじ":
                group_id = "nijisanji"
            else:
                group_id = video.get("group_id")    
            channel = video.get("channel")
            title = video.get("title")
            video_id = video.get("video_id")
            video_url = video.get("video_url")
            upload_url = video.get("upload_url")
            upload_title =get_video_metadata(upload_url).get("title", "Unknown")
            duration_minutes = video.get("duration_minutes", 0)
            duration = format_time(duration_minutes*60)
            total_comments = video.get("total_comments", 0)
            avg_comments_per_minute = video.get("avg_comments_per_minute", 0)
            max_comments_10sec = video.get("max_comments_10sec", 0)
            # 小数点1位までにフォーマット
            try:
                avg_comments_per_minute_fmt = f"{float(avg_comments_per_minute):.1f}"
            except Exception:
                avg_comments_per_minute_fmt = str(avg_comments_per_minute)
            try:
                max_comments_10sec_fmt = f"{float(max_comments_10sec):.1f}"
            except Exception:
                max_comments_10sec_fmt = str(max_comments_10sec)
            print(f"group_id: {group_id}, channel: {channel}, video_id: {video_id}, upload_url: {upload_url}")
            # 5. 画像パス取得とツイート
            sanitized_channel = sanitize_filename(channel)
            img_dir = os.path.join(os.path.dirname(__file__), "clips", sanitized_channel, video_id)
            if not os.path.exists(img_dir):
                print(f"画像ディレクトリが存在しません: {img_dir}")

            # twitter_で始まる画像ファイルを最大4つ取得
            imgs = [f for f in os.listdir(img_dir) if f.startswith("twitter_") and f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
            imgs = imgs[:4]
            img_paths = [os.path.join(img_dir, f) for f in imgs]
            if not img_paths:
                print("ツイート用画像が見つかりません")
            # ツイート内容例（元動画URLに変更）
            tweet_text = f"切り抜き元動画: {title}\n配信時間: {duration}\n合計コメント数: {total_comments}件\n平均コメント数（分）: {avg_comments_per_minute_fmt}件\n最大コメント数（10秒）: {max_comments_10sec_fmt}件\n元動画→ {video_url}"
            try:
                # v1.1 API認証（OAuth 1.0a）
                auth = tweepy.OAuth1UserHandler(
                    config.HOLOLIVE_api_key if group_id=="hololive" else config.NIJISANJI_api_key,
                    config.HOLOLIVE_api_secret if group_id=="hololive" else config.NIJISANJI_api_secret,
                    config.HOLOLIVE_access_token if group_id=="hololive" else config.NIJISANJI_access_token,
                    config.HOLOLIVE_access_token_secret if group_id=="hololive" else config.NIJISANJI_access_token_secret
                )
                api = tweepy.API(auth)
                media_ids = []
                for img_path in img_paths:
                    media = api.media_upload(img_path)
                    media_ids.append(media.media_id_string)

                # v2 API認証（Bearer Token）
                client = tweepy.Client(
                    consumer_key=config.HOLOLIVE_api_key if group_id=="hololive" else config.NIJISANJI_api_key,
                    consumer_secret=config.HOLOLIVE_api_secret if group_id=="hololive" else config.NIJISANJI_api_secret,
                    access_token=config.HOLOLIVE_access_token if group_id=="hololive" else config.NIJISANJI_access_token,
                    access_token_secret=config.HOLOLIVE_access_token_secret if group_id=="hololive" else config.NIJISANJI_access_token_secret
                )
                # 元ツイート投稿
                tweet_response = client.create_tweet(
                    text=tweet_text,
                    media_ids=media_ids
                )
                print(f"✓ Twitter画像付き投稿完了(v2): {tweet_text[:40]}... 画像数: {len(img_paths)}")

                # リプライ用ツイート内容
                reply_text = f"🎬 切り抜き動画\nタイトル：{upload_title}\nURL：{upload_url}"
                # サムネイル画像パス
                thumbnail_dir = os.path.join('g:/マイドライブ/clips', sanitized_channel, video_id)
                thumbnail_path = os.path.join(thumbnail_dir, 'サムネイル.png')
                reply_media_ids = []
                if os.path.exists(thumbnail_path):
                    try:
                        reply_media = api.media_upload(thumbnail_path)
                        reply_media_ids.append(reply_media.media_id_string)
                    except Exception as e:
                        print(f"サムネイル画像アップロード失敗: {e}")
                else:
                    print(f"サムネイル画像が見つかりません: {thumbnail_path}")

                # リプライ投稿（in_reply_to_tweet_id指定）
                client.create_tweet(
                    text=reply_text,
                    media_ids=reply_media_ids if reply_media_ids else None,
                    in_reply_to_tweet_id=tweet_response.data['id']
                )
                print(f"✓ 切り抜き動画リプライ投稿完了: {reply_text[:40]}... サムネイル: {bool(reply_media_ids)}")
            except Exception as e:
                import traceback
                print(f"Twitter画像投稿エラー: {e}")
                traceback.print_exc()
    if not found:
        print("本日18時公開予定の動画はありません")
        return
    
if __name__ == "__main__":
    main()