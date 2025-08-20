from chat_downloader import ChatDownloader
import time
from concurrent.futures import ThreadPoolExecutor

def get_comments(video_url, intro_duration_minutes=3, ending_duration_minutes=3, video_duration_minutes=None, is_premiere=None, premiere_offset=None):
    """chat-downloaderを使用してコメントを取得"""
    print("="*50)
    print("get_comments 関数開始")

    try:
        print(f"コメントの取得を開始: {video_url}")
        downloader = ChatDownloader()
        chat = downloader.get_chat(video_url)

        def process_message(message):
            timestamp = message.get('time_in_seconds', 0)
            text = message.get('message', '')
            if not text and 'message_elements' in message:
                text = ''.join(e['text'] for e in message['message_elements'] if e['type'] == 'text')
            author = message.get('author', {}).get('name', '')
            return {
                'timestamp': timestamp,
                'text': text,
                'author': author,
            }

        with ThreadPoolExecutor(max_workers=8) as executor:
            comments = list(executor.map(process_message, chat))

        for comment in comments:
            timestamp = comment['timestamp']
            comment['is_intro'] = timestamp < intro_duration_minutes * 60
            comment['is_ending'] = timestamp > (video_duration_minutes - ending_duration_minutes) * 60
        
        print(f"取得したコメント数: {len(comments)}")
        intro_count = sum(1 for c in comments if c['is_intro'])
        ending_count = sum(1 for c in comments if c['is_ending'])
        
        print(f"うち、導入部分({intro_duration_minutes}分以内)のコメント: {intro_count}件")
        print(f"うち、エンディング部分({ending_duration_minutes}分以内)のコメント: {ending_count}件")
        
        return comments
        
    except Exception as e:
        print(f"コメント取得エラー: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return []

def get_comments_for_timerange(video_url, start_time, end_time):
    """指定された時間範囲のコメントを取得"""
    try:
        downloader = ChatDownloader()
        chat = downloader.get_chat(video_url)
        
        comments = []
        for message in chat:
            timestamp = message.get('time_in_seconds', 0)
            
            # 指定範囲内のコメントのみを収集
            if start_time <= timestamp <= end_time:
                text = message.get('message', '')
                if not text and 'message_elements' in message:
                    text = ''.join(e['text'] for e in message['message_elements'] if e['type'] == 'text')
                
                comment = {
                    'timestamp': timestamp,
                    'text': text,
                    'author': message.get('author', {}).get('name', ''),
                }
                comments.append(comment)
            
            # 終了時間を過ぎたら終了
            elif timestamp > end_time:
                break
        
        return comments
        
    except Exception as e:
        print(f"時間範囲でのコメント取得エラー: {str(e)}")
        return []

def calculate_max_comments_per_interval(comments, duration_seconds, interval_seconds=10):
    """
    指定された時間間隔ごとのコメント数を計算し、最大値を返す
    
    Parameters:
    - comments: コメントのリスト
    - duration_seconds: 動画の総再生時間（秒）
    - interval_seconds: 集計する時間間隔（秒）
    
    Returns:
    - int: 最大コメント数
    """
    try:
        # コメントを時間でソート
        sorted_comments = sorted(comments, key=lambda x: x.get('timestamp', 0))
        
        # 時間間隔ごとのコメント数を集計
        intervals = {}
        for comment in sorted_comments:
            timestamp = comment.get('timestamp', 0)
            if timestamp < 0 or timestamp > duration_seconds:
                continue
                
            interval_index = int(timestamp // interval_seconds)
            intervals[interval_index] = intervals.get(interval_index, 0) + 1
        
        # 最大値を返す
        return max(intervals.values()) if intervals else 0
        
    except Exception as e:
        print(f"コメント集計エラー: {str(e)}")
        return 0

# === コメント選択アルゴリズム ===
from typing import List, Dict
import math

def is_stamp_only(comment: Dict) -> bool:
    """
    コメントがスタンプ（カスタム絵文字/emoji）のみで構成されているか判定
    - comment['elements'] が全て type=='custom_emoji' ならTrue
    - elementsがなければFalse
    """
    elements = comment.get('elements')
    if not elements or not isinstance(elements, list):
        return False
    return all(e.get('type') == 'custom_emoji' for e in elements)

def select_comments_per_second(comments: List[Dict], score_keys=None) -> List[Dict]:
    """
    1秒ごと・スコア帯ごと・スタンプのみコメントで最大件数を制限して選択
    Args:
        comments: コメント辞書リスト（timestamp, 各スコアキー, elementsを含む）
        score_keys: スコア判定に使うキーのリスト
    Returns:
        List[Dict]: 選択されたコメントリスト
    """
    if score_keys is None:
        score_keys = ['爆笑指数', 'かわいさ指数', '盛り上がり指数']

    grouped = {}
    for c in comments:
        sec = int(math.floor(c['timestamp']))
        grouped.setdefault(sec, []).append(c)

    selected = []
    for sec, group in grouped.items():
        # スコア帯ごと・スタンプのみで分類
        low, mid, high, stamps = [], [], [], []
        for c in sorted(group, key=lambda x: x['timestamp']):
            if is_stamp_only(c):
                stamps.append(c)
                continue
            score = max([c.get(k, 0) for k in score_keys])
            if score <= 1:
                low.append(c)
            elif 1 < score < 5:
                mid.append(c)
            elif score >= 5:
                high.append(c)
        selected += low[:10] + mid[:2] + high[:4] + stamps[:3]
    return sorted(selected, key=lambda x: x['timestamp'])
