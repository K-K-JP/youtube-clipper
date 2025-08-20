import os
import json
from datetime import datetime
def export_to_json(result, comments, duration_minutes, metadata, output_path=None):
    """
    全動画のサマリー情報を1つのJSONファイルで管理・更新する
    - result: analyzer_edit.py等で生成される統合結果(dict)
    - comments: コメントリスト（使わないが引数互換のため残す）
    - duration_minutes: 動画の長さ（分）
    - metadata: 動画メタデータ(dict)
    - output_path: 出力先ファイルパス（デフォルト: backend/data/summary_videos.json）
    """
    # デフォルト出力先を backend/data/summary_videos.json に変更
    if output_path is None:
        output_dir = os.path.join(os.path.dirname(__file__), 'data')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'summary_videos.json')
    # 必須情報を抽出
    video_id = result.get('video_id') or metadata.get('video_id') or 'unknown'
    channel = result.get('channel') or metadata.get('channel') or ''
    title = result.get('title') or metadata.get('title') or ''
    video_url = result.get('video_url') or metadata.get('video_url') or ''
    total_comments = result.get('totalComments') or len(comments) or 0
    duration = duration_minutes
    # 追加情報
    upload_date = metadata.get('upload_date') or result.get('upload_date') or ''
    weekday = metadata.get('weekday') or result.get('weekday') or ''
    avg_comments_per_minute = result.get('avg_comments_per_minute') or ''
    max_comments_10sec = result.get('max_comments_10sec') or ''
    clips = result.get('clips') if 'clips' in result else []
    # 配信のみ分析するためpublish_dateは不要
    group_name = result.get('group_name') or ''
    creator_eng = result.get('creator_eng') or metadata.get('creator_eng') or ''


    # 既存ファイルを読み込み
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except Exception:
                all_data = {}
    else:
        all_data = {}

    # サマリー情報を構築
    video_summary = {
        'channel': channel,
        'title': title,
        'video_url': video_url,
        'video_id': video_id,
        'duration_minutes': duration,
        'total_comments': total_comments,
        'upload_date': upload_date,
        'weekday': weekday,
        'avg_comments_per_minute': avg_comments_per_minute,
        'max_comments_10sec': max_comments_10sec,
        'clips': clips,
        'group_name': group_name,
        'creator_eng': creator_eng,
        'last_updated': datetime.now().isoformat(timespec='seconds')
    }

    all_data[video_id] = video_summary

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    print(f"✓ サマリーJSONを更新: {output_path} (動画ID: {video_id})")
    return {
        'output_json': output_path,
        'video_id': video_id
    }

if __name__ == "__main__":
    print("このモジュールは直接実行する用途はありません。analyzer_edit等からimportして使ってください。")
