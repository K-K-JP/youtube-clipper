import json
import os

def load_summary_videos(summary_path, video_id):
    """
    summary_videos.json から指定 video_id の clips リストを返す
    """
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"summary_videos.json not found: {summary_path}")
    with open(summary_path, encoding='utf-8') as f:
        data = json.load(f)
    return data.get(video_id, {}).get('clips', [])

def find_clip_meta(clips, start_sec, end_sec, tol=2.0):
    """
    clipsリストからstart_sec, end_secが一致するクリップのメタデータを返す（多少の誤差許容）
    """
    for c in clips:
        if abs(float(c.get('start', -1)) - float(start_sec)) < tol and abs(float(c.get('end', -1)) - float(end_sec)) < tol:
            return c
    return {}
