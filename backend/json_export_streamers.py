import os
import json
from datetime import datetime

def export_streamer_summary(result, comments, duration_minutes, metadata, output_path=None):
    """
    全配信者まとめ用のJSONを出力・更新する
    - result: analyzer_edit.py等で生成される統合結果(dict)
    - comments: コメントリスト
    - duration_minutes: 動画の長さ（分）
    - metadata: 動画メタデータ(dict)
    - output_path: 出力先ファイルパス（デフォルト: backend/data/summary_streamers.json）
    """
    # デフォルト出力先を backend/data/summary_streamers.json に変更
    if output_path is None:
        output_dir = os.path.join(os.path.dirname(__file__), 'data')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'summary_streamers.json')
    channel = result.get('channel') or metadata.get('channel') or ''
    if not channel:
        print('チャンネル名が取得できません')
        return

    # 既存ファイルを読み込み
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            try:
                all_data = json.load(f)
            except Exception:
                all_data = {}
    else:
        all_data = {}

    # チャンネルごとのデータを初期化
    if channel not in all_data:
        all_data[channel] = {
            'channel': channel,
            'group_name': result.get('group_name') or '',
            'videos': [],
            'total_comments': 0,
            'max_comments_10sec': 0,
            'max_total_comments': 0,
            'avg_total_comments_per_hour': 0,
            'analyzed_video_count': 0,
            'latest_analysis_date': '',
            'last_updated': ''
        }

    # 動画情報
    video_id = result.get('video_id') or metadata.get('video_id') or ''
    upload_date = metadata.get('upload_date') or result.get('upload_date') or ''
    title = result.get('title') or metadata.get('title') or ''
    duration = duration_minutes
    total_comments = result.get('totalComments') or len(comments) or 0
    max_comments_10sec = result.get('max_comments_10sec') or 0
    analysis_date = datetime.now().strftime('%Y-%m-%d')

    # 動画リストに追加
    all_data[channel]['videos'].append({
        'video_id': video_id,
        'title': title,
        'upload_date': upload_date,
        'duration_minutes': duration,
        'total_comments': total_comments,
        'max_comments_10sec': max_comments_10sec,
        'analysis_date': analysis_date
    })

    # 集計値を更新
    videos = all_data[channel]['videos']
    all_data[channel]['total_comments'] = sum(v['total_comments'] for v in videos)
    all_data[channel]['max_comments_10sec'] = max((v['max_comments_10sec'] for v in videos), default=0)
    all_data[channel]['max_total_comments'] = max((v['total_comments'] for v in videos), default=0)
    all_data[channel]['avg_total_comments_per_hour'] = round(
        sum(v['total_comments'] for v in videos) / max(len(videos),1) * 60 / max(sum(v['duration_minutes'] for v in videos),1), 2
    )
    all_data[channel]['analyzed_video_count'] = len(videos)
    all_data[channel]['latest_analysis_date'] = max((v['analysis_date'] for v in videos), default='')
    all_data[channel]['last_updated'] = datetime.now().isoformat(timespec='seconds')

    # int64→int変換
    import numpy as np
    def convert(obj):
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif hasattr(obj, 'item') and callable(obj.item):
            return obj.item()
        else:
            return obj
    def json_default(o):
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if hasattr(o, 'item') and callable(o.item):
            return o.item()
        raise TypeError(f'Object of type {type(o)} is not JSON serializable')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(convert(all_data), f, ensure_ascii=False, indent=2, default=json_default)

    print(f"✓ 配信者まとめJSONを更新: {output_path} (チャンネル: {channel})")
    return {
        'output_json': output_path,
        'channel': channel
    }

def build_streamer_summary_from_results(output_path=None):
    """
    process_videoのresult(dict)のリストから配信者ごとに集計し summary_streamers.json を一括生成する
    """
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), 'data', 'summary_streamers.json')
    # summary_videos.jsonから全動画情報を取得
    videos_path = os.path.join(os.path.dirname(__file__), 'data', 'summary_videos.json')
    if not os.path.exists(videos_path):
        print(f"summary_videos.jsonが見つかりません: {videos_path}")
        return
    with open(videos_path, 'r', encoding='utf-8') as f:
        all_videos = json.load(f)
    streamer_data = {}
    for v in all_videos.values():
        channel = v.get('channel') or ''
        if not channel:
            continue
        creator_eng = v.get('creator_eng', '')
        group_name = v.get('group_name', '')
        group_id = v.get('group_id', '')
        if channel not in streamer_data:
            streamer_data[channel] = {
                'channel': channel,
                'group_name': group_name,
                'group_id': group_id,
                'creator_eng': creator_eng,
                'videos': [],
                'total_comments': 0,
                'max_comments_10sec': 0,
                'max_total_comments': 0,
                'avg_total_comments_per_hour': 0,
                'analyzed_video_count': 0,
                'latest_analysis_date': '',
                'last_updated': ''
            }
        streamer_data[channel]['videos'].append({
            'video_id': v.get('video_id', ''),
            'title': v.get('title', ''),
            'upload_date': v.get('upload_date', ''),
            'duration_minutes': v.get('duration_minutes', 0),
            'total_comments': v.get('total_comments', 0),
            'max_comments_10sec': v.get('max_comments_10sec', 0),
            'analysis_date': v.get('last_updated', '')[:10]
        })
    # 集計値を計算
    for channel, data in streamer_data.items():
        videos = data['videos']
        data['total_comments'] = sum(v['total_comments'] for v in videos)
        data['max_comments_10sec'] = max((v['max_comments_10sec'] for v in videos), default=0)
        data['max_total_comments'] = max((v['total_comments'] for v in videos), default=0)
        total_minutes = sum(v['duration_minutes'] for v in videos)
        data['avg_total_comments_per_hour'] = round(
            sum(v['total_comments'] for v in videos) * 60 / max(total_minutes,1), 2
        )
        data['analyzed_video_count'] = len(videos)
        data['latest_analysis_date'] = max((v['analysis_date'] for v in videos), default='')
        data['last_updated'] = datetime.now().isoformat(timespec='seconds')
    # int64→int変換
    import numpy as np
    def convert(obj):
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif hasattr(obj, 'item') and callable(obj.item):
            return obj.item()
        else:
            return obj
    def json_default(o):
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if hasattr(o, 'item') and callable(o.item):
            return o.item()
        raise TypeError(f'Object of type {type(o)} is not JSON serializable')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(convert(streamer_data), f, ensure_ascii=False, indent=2, default=json_default)
    print(f"✓ summary_videos.jsonから summary_streamers.json を再構築しました: {output_path}")

if __name__ == "__main__":
    print("このモジュールは直接実行する用途はありません。analyzer_edit等からimportして使ってください。")
