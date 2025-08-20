import os
import json
import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import pytz

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]

# ----------------------------
# 認証 & APIクライアント作成（ユーザー選択対応）
# ----------------------------
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

        # トークン保存
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ----------------------------
# summary_videos.jsonから予約投稿日時を取得・設定
# ----------------------------
def get_and_set_scheduled_publish_time(video_id, summary_json_path):
    """
    summary_videos.jsonから該当video_idの予約投稿日時を取得し、
    未来なら翌日18時JST、過去なら最も近い18時JSTに調整し、
    その値をjsonに書き戻す。返り値はISO8601(UTC)文字列。
    """
    with open(summary_json_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    video_entry = summary.get(video_id)
    if not video_entry:
        raise ValueError(f"video_id {video_id} not found in summary_videos.json")

    # 予約投稿日時の取得（なければNone）
    scheduled_key = "scheduled_publish_time"
    prev_scheduled = video_entry.get(scheduled_key)
    now = datetime.datetime.now(pytz.timezone("Asia/Tokyo"))

    # 既存の予約投稿日時があればパース
    if prev_scheduled:
        try:
            prev_dt = datetime.datetime.fromisoformat(prev_scheduled)
            if prev_dt.tzinfo is None:
                prev_dt = pytz.timezone("Asia/Tokyo").localize(prev_dt)
        except Exception:
            prev_dt = None
    else:
        prev_dt = None

    # ロジック分岐
    if prev_dt and prev_dt > now:
        # 未来→翌日18時
        base_date = (prev_dt + datetime.timedelta(days=1)).date()
    elif prev_dt:
        # 過去→その日付の18時以降で一番近い18時
        if now.hour < 18:
            base_date = now.date()
        else:
            base_date = (now + datetime.timedelta(days=1)).date()
    else:
        # 予約投稿日時が未設定→今日18時 or 明日18時
        if now.hour < 18:
            base_date = now.date()
        else:
            base_date = (now + datetime.timedelta(days=1)).date()

    scheduled_jst = datetime.datetime.combine(base_date, datetime.time(18, 0, 0))
    scheduled_jst = pytz.timezone("Asia/Tokyo").localize(scheduled_jst)
    scheduled_utc = scheduled_jst.astimezone(pytz.utc)
    scheduled_iso = scheduled_utc.isoformat()

    # jsonに書き戻し
    video_entry[scheduled_key] = scheduled_iso
    summary[video_id] = video_entry
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"✓ 予約投稿日時（JST）: {scheduled_jst}")
    return scheduled_iso

# ----------------------------
# ファイル選択ダイアログ
# ----------------------------
def choose_file(title, filetypes):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(title=title, filetypes=filetypes)

# ----------------------------
# 字幕アップロード
# ----------------------------
def upload_caption(youtube, video_id, lang_code, name, filepath):
    insert_result = youtube.captions().insert(
        part="snippet",
        body=dict(
            snippet=dict(
                videoId=video_id,
                language=lang_code,
                name=name,
                isDraft=False
            )
        ),
        media_body=MediaFileUpload(filepath)
    ).execute()
    print(f"✓ 字幕アップロード: {lang_code}")

# ----------------------------
def main():
    # 動画ファイルのパスをGUIで選択
    video_path = choose_file("アップロードする動画ファイルを選択", [("MP4 files", "*.mp4"), ("All files", "*.*")])
    if not video_path:
        print("動画ファイルのパスが選択されませんでした。")
        return

    # video_idは動画ファイルの2階層上のフォルダ名
    # 例: .../clips/チャンネル名/動画ID/動画ファイル.mp4
    video_folder = os.path.dirname(video_path)
    video_id = os.path.basename(video_folder)
    summary_json_path = os.path.join(os.path.dirname(__file__), "data", "summary_videos.json")

    # summary_videos.jsonからgroup_id取得
    with open(summary_json_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    video_entry = summary.get(video_id)
    if not video_entry:
        print(f"summary_videos.jsonにvideo_id {video_id} が見つかりません"); return
    group_id = None
    clips = video_entry.get("clips", [])
    if clips and "group_id" in clips[0]:
        group_id = clips[0]["group_id"]
    if not group_id:
        print(f"group_idがsummary_videos.jsonにありません: {video_id}"); return

    # サムネイル・概要欄・字幕ファイル
    folder = os.path.dirname(video_path)
    thumb_path = choose_file("サムネイル画像ファイルを選択", [("Image files", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif"), ("All files", "*.*")])
    description_path = os.path.join(folder, "概要欄.txt")
    caption_files = {
        "en-US": os.path.join(folder, "tra_eng.srt"),
        "id": os.path.join(folder, "tra_ind.srt"),
        "zh-TW": os.path.join(folder, "tra_tai.srt"),
    }
    if not os.path.exists(description_path):
        print("概要欄ファイルが見つかりません。"); return
    with open(description_path, "r", encoding="utf-8") as f:
        description = f.read()

    title = os.path.splitext(os.path.basename(video_path))[0]
    scheduled_publish_time = get_and_set_scheduled_publish_time(video_id, summary_json_path)
    print(f"✓ 公開予約日時（UTC）: {scheduled_publish_time}")

    # group_idに基づいてタグを設定
    def get_tags_by_group_id(group_id):
        base_tags = ["切り抜き", "Vtuber clips"]
        if group_id == "hololive":
            base_tags.extend(["ホロライブ", "hololive"])
        elif group_id == "nijisanji":
            base_tags.extend(["にじさんじ", "nijisanji"])
        return base_tags
    tags = get_tags_by_group_id(group_id)

    youtube = get_authenticated_service(group_id)

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "20",  # ゲーム
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


    media_file = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    upload_request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media_file
    )
    response = upload_request.execute()
    uploaded_video_id = response["id"]
    upload_url = f"https://www.youtube.com/watch?v={uploaded_video_id}"
    print(f"✓ 動画アップロード完了: {upload_url}")

    # サムネイル（選択されていれば設定）
    if thumb_path:
        youtube.thumbnails().set(
            videoId=uploaded_video_id,
            media_body=MediaFileUpload(thumb_path)
        ).execute()
        print("✓ サムネイル設定完了")
    else:
        print("サムネイル画像が選択されなかったため、設定をスキップします。")

    # 字幕
    for lang_code, path in caption_files.items():
        if os.path.exists(path):
            name = f"Caption ({lang_code})"
            upload_caption(youtube, uploaded_video_id, lang_code, name, path)
        else:
            print(f"⚠ 字幕ファイルが見つかりません: {path}")

    print("✅ アップロード完了！")

    # アップロード情報をsummary_videos.jsonに追記
    video_entry["uploaded_youtube_url"] = upload_url
    with open(summary_json_path, "w", encoding="utf-8") as f:
        summary[video_id] = video_entry
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Webサイト生成処理を呼び出す（必要なら）
    # try:
    #     from generate_chart_pages import generate_chart_html_pages
    #     from generate_creator_pages import generate_creator_html_pages
    #     generate_chart_html_pages()
    #     generate_creator_html_pages()
    # except Exception as e:
    #     print(f"Webサイト生成処理でエラー: {e}")


if __name__ == "__main__":
    main()
