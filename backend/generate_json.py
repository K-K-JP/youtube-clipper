import json
import os
from collections import defaultdict
import datetime

from analyzer import sanitize_filename, calculate_max_comments_per_interval

# Paths for data files
VIDEOS_JSON_PATH = "docs/data/videos.json"
CREATORS_JSON_PATH = "docs/data/creators.json"

def update_json_data_for_video(video_metadata, comments):
    """
    Updates videos.json and creators.json with data for a single video.

    Args:
        video_metadata (dict): Dictionary containing video metadata (title, video_id, channel, duration_seconds, etc.).
        comments (list): List of comments for the video.
    """
    # Ensure data directory exists
    os.makedirs(os.path.dirname(VIDEOS_JSON_PATH), exist_ok=True)

    video_id = video_metadata.get('video_id')
    channel_name = video_metadata.get('channel')
    sanitized_channel_name = sanitize_filename(channel_name)

    # Calculate stats for videos.json
    total_comments = len(comments)
    duration_seconds = video_metadata.get('duration', 0) # duration from metadata is in seconds
    duration_minutes = duration_seconds / 60 if duration_seconds > 0 else 0

    avg_comments_per_min = round(total_comments / duration_minutes, 2) if duration_minutes > 0 else 0
    max_comments_per_10s = calculate_max_comments_per_interval(comments, duration_seconds, 10)

    # Format duration for display (HH:MM:SS)
    h, m, s = str(datetime.timedelta(seconds=int(duration_seconds))).split(':')
    formatted_duration = f"{int(h)}時間{int(m)}分{int(s)}秒" if int(h) > 0 else f"{int(m)}分{int(s)}秒"

    # --- Update videos.json ---
    videos_data = []
    if os.path.exists(VIDEOS_JSON_PATH):
        with open(VIDEOS_JSON_PATH, "r", encoding="utf-8") as f:
            try:
                videos_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: {VIDEOS_JSON_PATH} is empty or malformed. Starting fresh.")
                videos_data = []

    new_video_entry = {
        "creator": sanitized_channel_name,
        "video_id": video_id,
        "title": video_metadata.get('title', ''),
        "date": video_metadata.get('upload_date', ''), # YYYY-MM-DD
        "duration": formatted_duration, # Formatted string
        "duration_seconds": duration_seconds, # Raw seconds for calculations
        "total_comments": total_comments,
        "avg_comments_per_min": avg_comments_per_min,
        "max_comments_per_10s": max_comments_per_10s,
        "cut_link": "", # This will be updated by sheets_export or manually
        "original_url": f"https://www.youtube.com/watch?v={video_id}",
        "chart_url": f"backend/clips/chart_pages/{video_id}.html", # Relative path for web
        "creator_page": f"{sanitized_channel_name}.html"
    }

    found_video = False
    for i, video in enumerate(videos_data):
        if video.get("video_id") == video_id:
            videos_data[i] = new_video_entry # Overwrite existing
            found_video = True
            break
    if not found_video:
        videos_data.append(new_video_entry) # Add new

    with open(VIDEOS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(videos_data, f, ensure_ascii=False, indent=2)
    print(f"✅ {VIDEOS_JSON_PATH} updated for video ID: {video_id}")

    # --- Update creators.json ---
    creators_data = []
    if os.path.exists(CREATORS_JSON_PATH):
        with open(CREATORS_JSON_PATH, "r", encoding="utf-8") as f:
            try:
                creators_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: {CREATORS_JSON_PATH} is empty or malformed. Starting fresh.")
                creators_data = []

    # 既存のcreators_dataから、現在のchannel_nameに対応するcreator_pageのファイル名部分を取得
    # generate_json_all.pyで生成されたcreators.jsonにはcreator_pageが含まれているはず
    english_creator_name = sanitized_channel_name # デフォルト値
    for existing_creator in creators_data:
        if existing_creator.get("name") == channel_name:
            if existing_creator.get("creator_page"):
                # .htmlを除いたファイル名部分を取得
                english_creator_name = existing_creator["creator_page"].replace(".html", "")
            break

    # Recalculate stats for the specific creator based on all their videos in videos_data
    creator_videos = [v for v in videos_data if v.get("creator") == sanitized_channel_name]

    total_comments_sum = sum(v.get("total_comments", 0) for v in creator_videos)
    total_duration_seconds_for_creator = sum(
        v.get("duration_seconds", 0) for v in creator_videos
    )

    avg_comments_per_hour_creator = round(total_comments_sum / (total_duration_seconds_for_creator / 3600), 2) if total_duration_seconds_for_creator > 0 else 0

    max_comments_per_10s_creator = max(v.get("max_comments_per_10s", 0) for v in creator_videos) if creator_videos else 0

    # Calculate max comments per hour for creator
    max_comments_per_hour_creator = 0
    if creator_videos:
        for v in creator_videos:
            if v.get("duration_seconds", 0) > 0:
                current_video_comments_per_hour = v.get("total_comments", 0) / (v.get("duration_seconds") / 3600)
                if current_video_comments_per_hour > max_comments_per_hour_creator:
                    max_comments_per_hour_creator = current_video_comments_per_hour
    max_comments_per_hour_creator = round(max_comments_per_hour_creator, 2)

    video_count_creator = len(creator_videos)
    latest_analysis_date = max(v.get("date", "") for v in creator_videos) if creator_videos else "" # Assuming 'date' is YYYY-MM-DD

    new_creator_entry = {
        "name": channel_name,
        "group": "ホロライブ", # Assuming only hololive for now based on previous conversation
        "average_comments_per_hour": avg_comments_per_hour_creator,
        "max_comments_per_10s": max_comments_per_10s_creator,
        "max_comments_per_hour": max_comments_per_hour_creator,
        "video_count": video_count_creator,
        "last_updated": latest_analysis_date,
        "creator_page": f"{english_creator_name}.html", # 修正
        "icon_url": f"../static/images/creators/{english_creator_name}.png" # 修正
    }

    found_creator = False
    for i, creator in enumerate(creators_data):
        if creator.get("name") == channel_name:
            creators_data[i] = new_creator_entry # Overwrite existing
            found_creator = True
            break
    if not found_creator:
        creators_data.append(new_creator_entry) # Add new

    with open(CREATORS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(creators_data, f, ensure_ascii=False, indent=2)
    print(f"✅ {CREATORS_JSON_PATH} updated for creator: {channel_name}")
