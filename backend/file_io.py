import json
import os
import time
import math
import re
from collections import defaultdict
from utility import sanitize_filename, get_video_id_from_url, seconds_to_hms

def get_comments_cache_path(video_url):
    """コメントキャッシュファイルのパスを取得"""
    video_id = get_video_id_from_url(video_url)
    cache_dir = os.path.join('backend', 'clips', 'cache')
    return os.path.join(cache_dir, f'{video_id}_comments_cache.json')

def save_comments_to_cache(video_url, comments):
    """コメントをキャッシュに保存"""
    cache_path = get_comments_cache_path(video_url)
    try:
        cache_data = {
            'video_url': video_url,
            'timestamp': time.time(),
            'comments': comments
        }
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"コメントをキャッシュに保存: {len(comments)}件 -> {cache_path}")
    except Exception as e:
        print(f"キャッシュ保存エラー: {e}")

def load_comments_from_cache(video_url):
    """キャッシュからコメントを読み込み"""
    cache_path = get_comments_cache_path(video_url)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"キャッシュからコメントを読み込み: {len(data['comments'])}件")
                return data['comments']
        except Exception as e:
            print(f"キャッシュ読み込みエラー: {e}")
    return None

def generate_chart_data_from_comments(video_url, comments, interval=10):
    """コメントリストからチャート用データを生成して保存"""
    # 1. 動画ID取得
    video_id = get_video_id_from_url(video_url)

    # 2. ディレクトリ・パス設定
    chart_dir = os.path.join('backend', 'clips', 'chart_data')
    os.makedirs(chart_dir, exist_ok=True)
    output_path = os.path.join(chart_dir, f"{video_id}_chart.json")

    # 3. 集計
    comment_bins = defaultdict(int)
    max_time = 0
    for comment in comments:
        t = comment.get("timestamp", 0)
        if t < 0:
            continue  # 本編外は除く
        bin_index = math.floor(t / interval)
        comment_bins[bin_index] += 1
        max_time = max(max_time, t)

    chart_data = [
        {"time": i * interval, "count": comment_bins[i]}
        for i in range(0, math.ceil(max_time / interval) + 1)
    ]

    # 4. 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(chart_data, f, ensure_ascii=False, indent=2)

    print(f"チャート用データを保存: {output_path}")

def save_emoji_dict(emoji_dict: dict, video_id: str, channel_name: str):
    """絵文字辞書をJSONで保存"""
    if not emoji_dict:
        print(f"No custom emojis found. Skipping save.")
        return

    sanitized_name = sanitize_filename(channel_name)
    emoji_dict_dir = os.path.join('backend', 'clips', 'emoji_dict')
    os.makedirs(emoji_dict_dir, exist_ok=True)

    filename = f"{sanitized_name}_emoji.json"
    filepath = os.path.join(emoji_dict_dir, filename)

    # 既存の辞書を読み込み
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                existing_dict = json.load(f)
        except Exception as e:
            print(f"Failed to load existing emoji dictionary: {e}")
            existing_dict = {}
    else:
        existing_dict = {}

    # 新規の絵文字のみ追加
    new_entries = 0
    for shortcut, emoji_data in emoji_dict.items():
        if shortcut not in existing_dict:
            existing_dict[shortcut] = emoji_data
            new_entries += 1

    if new_entries == 0:
        print(f"No new emojis to add. Skipping save.")
        return

    # 保存
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(existing_dict, f, ensure_ascii=False, indent=2)
        print(f"Saved {new_entries} new emojis → {filepath}")
    except Exception as e:
        print(f"Failed to save emoji dictionary: {e}")

def generate_clip_urls_txt(video_url, excitement_periods, output_dir='backend/clips', video_title='', channel_name=''):
    """クリップのタイムスタンプリストをTXTファイルに出力"""
    try:
        # 出力ファイルパス
        sanitized_title = sanitize_filename(video_title)
        txt_filename = "概要欄.txt"
        video_id = get_video_id_from_url(video_url)
        if not video_id:
            return {"error": "無効な動画URLです"}

        if channel_name:
            channel_dir = os.path.join(output_dir, sanitize_filename(channel_name))
            video_specific_dir = os.path.join(channel_dir, video_id)
            if not os.path.exists(channel_dir):
                os.makedirs(channel_dir, exist_ok=True)
            if not os.path.exists(video_specific_dir):
                os.makedirs(video_specific_dir, exist_ok=True)
            txt_path = os.path.join(video_specific_dir, txt_filename)
        else:
            txt_path = os.path.join(output_dir, txt_filename)

        # 固定の継続時間
        OP_DURATION = 13.833
        EYECATCH_1_DURATION = 3.000
        EYECATCH_2_DURATION = 3.133
        EYECATCH_3_DURATION = 3.000
        ED_DURATION = 15.033

        # excitement_periodsはcombine_orderの順番で渡されることを想定
        # クリップの継続時間・タイトルを取得
        clip_durations = []
        clip_titles = []
        for period in excitement_periods:
            duration = period['end'] - period['start']
            # タイトル例: "笑い1位" "癒し2位" "カオス3位" など
            label = period.get('main_label', '')
            rank = period.get('rank', '')
            if label and rank:
                title = f"{label}_{rank}位"
            elif rank:
                title = f"{rank}位"
            else:
                title = label or "クリップ"
            clip_durations.append(duration)
            clip_titles.append(title)

        # 累積時間でタイムスタンプを計算（combine_order順）
        current_time = 0
        timestamps = []


        # オープニング
        timestamps.append(("オープニング", seconds_to_hms(current_time)))
        current_time += OP_DURATION

        # 1番目のアイキャッチ（タイトルなしでスキップ）
        current_time += EYECATCH_1_DURATION

        # クリップ（combine_order順）
        for i, (duration, title) in enumerate(zip(clip_durations, clip_titles)):
            timestamps.append((title, seconds_to_hms(current_time)))
            current_time += duration
            # 2番目・3番目のアイキャッチを適切な位置で挿入（例: 3分割）
            if i + 1 == len(clip_durations) // 3:
                current_time += EYECATCH_2_DURATION
            elif i + 1 == 2 * len(clip_durations) // 3:
                current_time += EYECATCH_3_DURATION

        # エンディング
        timestamps.append(("エンディング", seconds_to_hms(current_time)))

        # TXTファイルに出力
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("配信タイトル\n")
            f.write(f"{video_title}\n\n")
            f.write("配信URL\n")
            f.write(f"{video_url}\n\n")
            f.write("タイムスタンプ一覧\n")
            for title, timestamp in timestamps:
                f.write(f"{timestamp} {title}\n")

        print(f"タイムスタンプリストを出力: {txt_path}")
        return {"success": True, "file_path": txt_path}

    except Exception as e:
        print(f"クリップURL出力エラー: {str(e)}")
        return {"error": str(e)}

def extract_shortcuts_from_chat_downloader_json(json_path: str) -> set:
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load chat-downloader JSON: {e}")
        return set()

    comments = data.get("comments", [])
    shortcuts = set()

    for comment in comments:
        matches = re.findall(r':[a-zA-Z0-9_]+:', comment.get("text", ""))
        shortcuts.update(matches)

    return shortcuts

def extract_all_text_comments(actions: list) -> list:
    comments = []
    for action in actions:
        if "addChatItemAction" not in action:
            continue
        item = action["addChatItemAction"].get("item", {})
        renderer = item.get("liveChatTextMessageRenderer")
        if renderer:
            comments.append(renderer)
    return comments