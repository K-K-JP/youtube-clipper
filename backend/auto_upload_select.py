# --- Imports ---
import os
import json
import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import config

# --- Twitter自動投稿 ---
import tweepy


# --- 予約投稿日時取得ロジック ---
import datetime
import pytz

def get_and_set_scheduled_publish_time(video_id, summary_json_path):
    with open(summary_json_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    video_entry = summary.get(video_id)
    if not video_entry:
        raise ValueError(f"video_id {video_id} not found in summary_videos.json")
    scheduled_key = "scheduled_publish_time"
    prev_scheduled = video_entry.get(scheduled_key)
    now = datetime.datetime.now(pytz.timezone("Asia/Tokyo"))
    if prev_scheduled:
        try:
            prev_dt = datetime.datetime.fromisoformat(prev_scheduled)
            if prev_dt.tzinfo is None:
                prev_dt = pytz.timezone("Asia/Tokyo").localize(prev_dt)
        except Exception:
            prev_dt = None
    else:
        prev_dt = None
    if prev_dt and prev_dt > now:
        base_date = (prev_dt + datetime.timedelta(days=1)).date()
    elif prev_dt:
        if now.hour < 18:
            base_date = now.date()
        else:
            base_date = (now + datetime.timedelta(days=1)).date()
    else:
        if now.hour < 18:
            base_date = now.date()
        else:
            base_date = (now + datetime.timedelta(days=1)).date()
    scheduled_jst = datetime.datetime.combine(base_date, datetime.time(18, 0, 0))
    scheduled_jst = pytz.timezone("Asia/Tokyo").localize(scheduled_jst)
    scheduled_utc = scheduled_jst.astimezone(pytz.utc)
    scheduled_iso = scheduled_utc.isoformat()
    video_entry[scheduled_key] = scheduled_iso
    summary[video_id] = video_entry
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"✓ 予約投稿日時（JST）: {scheduled_jst}")
    return scheduled_iso


# --- Google Sheets認証・データ取得 ---

# create_clip_sheet.pyと同じ認証方式
service_account_path = os.path.join('backend', 'service_account.json')
gc = gspread.service_account(filename=service_account_path)
spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
sheet = spreadsheet.worksheet('入力用')
records = sheet.get_all_records()
selected_rows = []

# --- ファイル探索 ---
def find_files(channel, video_id):
    base_path = f"g:/マイドライブ/clips/{channel}/{video_id}/"
    video_file = None
    thumbnail_file = None
    description_file = None
    short_files = []
    if os.path.exists(base_path):
        for fname in os.listdir(base_path):
            if fname.startswith(f"combined_{video_id}") and fname.endswith(".mp4"):
                video_file = os.path.join(base_path, fname)
            elif fname == "サムネイル.png":
                thumbnail_file = os.path.join(base_path, fname)
            elif fname == "概要欄.txt":
                description_file = os.path.join(base_path, fname)
            elif fname.startswith("short__") and fname.endswith(".mp4"):
                short_files.append(os.path.join(base_path, fname))
    short_files = sorted(short_files)[:4]  # 最大4つ
    return video_file, thumbnail_file, description_file, short_files

# --- YouTube認証・アップロード ---
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
def get_authenticated_service(user_id="default"):
    token_path = f"backend/token_{user_id}.json"
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("backend/client_secrets.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(channel, group_id, video_id, video_file, thumbnail_file, description_file, short_files):
    if not (video_file and thumbnail_file and description_file):
        print(f"必要なファイルが揃っていません: {channel}/{video_id}")
        return
    with open(description_file, "r", encoding="utf-8") as f:
        description = f.read()
    tags = ["切り抜き", "Vtuber clips", channel]
    youtube = get_authenticated_service(group_id)
    # 予約投稿日時取得
    summary_json_path = os.path.join(os.path.dirname(__file__), "data", "summary_videos.json")
    scheduled_publish_time = get_and_set_scheduled_publish_time(video_id, summary_json_path)
    # --- combine_動画アップロード ---
    title = os.path.splitext(os.path.basename(video_file))[0]
    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "20",
            "tags": tags,
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": scheduled_publish_time,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
            "publicStatsViewable": True
        }
    }
    media_file = MediaFileUpload(video_file, mimetype="video/mp4", resumable=True)
    upload_request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media_file
    )
    response = upload_request.execute()
    uploaded_video_id = response["id"]
    upload_url = f"https://www.youtube.com/watch?v={uploaded_video_id}"
    print(f"✓ 動画アップロード完了: {upload_url}")
    # summary_videos.jsonにURLも保存
    try:
        with open(summary_json_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        video_id_str = str(video_id)
        video_entry = summary.get(video_id_str, {})
        video_entry["upload_url"] = upload_url
        summary[video_id_str] = video_entry
        with open(summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"✓ 動画URLをsummary_videos.jsonに保存: {upload_url}")
    except Exception as e:
        print(f"動画URL保存エラー: {e}")
    youtube.thumbnails().set(
        videoId=uploaded_video_id,
        media_body=MediaFileUpload(thumbnail_file)
    ).execute()
    print("✓ サムネイル設定完了")
    print("✅ アップロード完了！")
    # アップロード完了後、該当行の投稿完了フラグ（G列）をTRUEに変更
    try:
        all_values = sheet.get_all_values()
        for idx, row in enumerate(all_values[1:], start=2):
            if row[2] == video_id:
                # 投稿完了フラグをTRUEに更新
                sheet.update_acell(f"G{idx}", "TRUE")
                print(f"✓ 投稿完了フラグをTRUEにしました (G{idx})")
                # 行グレーアウト（任意）
                try:
                    sheet.format(f"A{idx}:S{idx}", {"backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}})
                    print(f"✓ シート行 {idx} をグレーアウトしました")
                except Exception as e:
                    print(f"グレーアウト処理でエラー: {e}")
                break
    except Exception as e:
        print(f"投稿完了フラグ更新でエラー: {e}")

    # --- short__動画アップロード（最大3つ） ---
    # 投稿時間計算
    try:
        scheduled_dt = datetime.datetime.fromisoformat(scheduled_publish_time.replace('Z', '+00:00'))
    except Exception:
        scheduled_dt = None
    short_times = []
    if scheduled_dt:
        jst = pytz.timezone("Asia/Tokyo")
        dt_jst = scheduled_dt.astimezone(jst)
        # 1本目: 当日19:30
        short_times.append(dt_jst.replace(hour=19, minute=30, second=0, microsecond=0))
        # 2本目: 当日22:00
        short_times.append(dt_jst.replace(hour=22, minute=0, second=0, microsecond=0))
        # 翌日
        next_day = dt_jst + datetime.timedelta(days=1)
        # 3本目: 翌日8:15
        short_times.append(next_day.replace(hour=8, minute=15, second=0, microsecond=0))
        # 4本目: 翌日12:00
        short_times.append(next_day.replace(hour=12, minute=0, second=0, microsecond=0))
    # --- 概要欄はcombine_と同じ ---
    for i, short_file in enumerate(short_files):
        if i >= 4:
            break
        # short__{タイトル} → {タイトル} だけにする
        base_title = os.path.splitext(os.path.basename(short_file))[0]
        if base_title.startswith("short__"):
            short_title = base_title[7:]
        else:
            short_title = base_title
        # 投稿時間（UTC）
        if scheduled_dt:
            publish_jst = short_times[i]
            publish_utc = publish_jst.astimezone(pytz.utc)
            publish_iso = publish_utc.isoformat()
        else:
            publish_iso = scheduled_publish_time
        short_request_body = {
            "snippet": {
                "title": short_title,
                "description": description,
                "categoryId": "20",
                "tags": tags,
                "defaultLanguage": "ja",
                "defaultAudioLanguage": "ja"
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_iso,
                "selfDeclaredMadeForKids": False,
                "embeddable": True,
                "publicStatsViewable": True
            }
        }
        short_media_file = MediaFileUpload(short_file, mimetype="video/mp4", resumable=True)
        short_upload_request = youtube.videos().insert(
            part="snippet,status",
            body=short_request_body,
            media_body=short_media_file
        )
        short_response = short_upload_request.execute()
        short_uploaded_video_id = short_response["id"]
        short_upload_url = f"https://www.youtube.com/watch?v={short_uploaded_video_id}"
        print(f"✓ short動画アップロード完了: {short_upload_url} (予定時刻: {publish_iso})")
        # youtube.thumbnails().set(
        #     videoId=short_uploaded_video_id,
        #     media_body=MediaFileUpload(thumbnail_file)
        # ).execute()
        # print("✓ short動画サムネイル設定完了")

# --- main関数 ---
def main():
    for row in records:
        if row.get('分析フラグ') == "TRUE" and row.get('結合フラグ') == "TRUE" and row.get('投稿フラグ') == "TRUE" and row.get('投稿完了フラグ') != "TRUE":
            channel = row.get('チャンネル名')
            video_id = row.get('シート')
            group_id = row.get('グループID')
            selected_rows.append({'channel': channel, 'video_id': video_id, 'group_id': group_id})
        else:
            print(f"[DEBUG] スキップ: {row.get('シート')} (分析フラグ: {row.get('分析フラグ')}, 結合フラグ: {row.get('結合フラグ')}, 投稿フラグ: {row.get('投稿フラグ')})")
    for row in selected_rows:
        channel = row['channel']
        video_id = row['video_id']
        group_id = row['group_id']
        print(f"[DEBUG] 処理対象: {channel}/{group_id}/{video_id}")
        video_file, thumbnail_file, description_file, short_files = find_files(channel, video_id)
        print(f"動画: {video_file}\nサムネ: {thumbnail_file}\n概要欄: {description_file}")
        upload_to_youtube(channel, group_id,video_id, video_file, thumbnail_file, description_file, short_files)

# --- エントリーポイント ---
if __name__ == "__main__":
    main()
