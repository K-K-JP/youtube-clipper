def safe_float(val):
    import pandas as pd
    try:
        if pd.isna(val) or val is None:
            return 0.0
        return float(val)
    except Exception:
        return 0.0

def safe_int(val):
    import pandas as pd
    try:
        if pd.isna(val) or val is None:
            return 0
        return int(val)
    except Exception:
        return 0
def error_result(message, extra=None):
    result = {
        'clips': [],
        'error': message
    }
    if extra:
        result.update(extra)
    return result
import subprocess

def get_codec_info(file_path):
    # 映像情報の取得
    video_result = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,width,height,r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    video_info = video_result.stdout.decode().strip().split('\n')

    # 音声情報の取得
    audio_result = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name,channels,sample_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    audio_info = audio_result.stdout.decode().strip().split('\n')

    print("🎥 映像情報:")
    print(f"  コーデック    : {video_info[0]}")
    print(f"  解像度        : {video_info[1]}x{video_info[2]}")
    print(f"  フレームレート: {video_info[3]}")

    print("🔊 音声情報:")
    print(f"  コーデック    : {audio_info[0]}")
    print(f"  チャンネル数  : {audio_info[1]}")
    print(f"  サンプリングレート: {audio_info[2]} Hz")
import re
import os
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import timedelta
import hashlib

def sanitize_filename(filename):
    """ファイル名に使用できない文字を削除"""
    # ファイル名に使用できない文字を置換
    invalid_chars = r'[\\/*?:"<>|]'
    sanitized = re.sub(invalid_chars, '', filename)
    
    # 長すぎるファイル名を切り詰め
    if len(sanitized) > 100:
        sanitized = sanitized[:97] + '...'
        
    # 空白を置換
    sanitized = sanitized.replace(' ', '_')
    
    return sanitized

def extract_video_id(video_url):
    """YouTubeのURLからビデオIDを抽出"""
    if "youtube.com/watch?v=" in video_url:
        return video_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in video_url:
        return video_url.split("youtu.be/")[1].split("?")[0]
    return None

def get_video_id_from_url(video_url):
    """動画URLから動画IDを抽出"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, video_url)
        if match:
            return match.group(1)
    # URLから動画IDが取得できない場合はハッシュを使用
    return hashlib.md5(video_url.encode()).hexdigest()[:11]

def setup_japanese_font():
    """日本語フォントを設定"""
    if os.name == 'nt':
        plt.rcParams['font.family'] = 'MS Gothic'
    else:
        fonts = fm.findSystemFonts()
        japanese_fonts = [f for f in fonts if 'japan' in f.lower() or 'noto' in f.lower()]
        if japanese_fonts:
            plt.rcParams['font.family'] = fm.FontProperties(fname=japanese_fonts[0]).get_name()
    plt.rcParams['axes.unicode_minus'] = False

def format_srt_timestamp(seconds):
    """SRT形式のタイムスタンプを生成"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    ms = int(round((seconds - total_seconds) * 1000))
    h, remainder = divmod(total_seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def format_time(seconds):
    """秒を時分秒形式に変換（3600以上はhh:mm:ss形式）"""
    seconds = int(seconds)
    if seconds >= 3600:
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"

def seconds_to_hms(seconds):
    """秒をHH:MM:SS形式に変換"""
    return str(timedelta(seconds=int(seconds)))

def time_to_seconds(time_str):
    """時間文字列を秒数に変換"""
    if not isinstance(time_str, str):
        return time_str  # すでに数値の場合はそのまま返す
    
    # 「0:10:25」形式を秒数に変換
    parts = time_str.split(':')
    if len(parts) == 3:  # HH:MM:SS
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:  # MM:SS
        m, s = parts
        return int(m) * 60 + float(s)
    else:  # SS または数値に変換可能な文字列
        return float(time_str)

def seconds_to_ass_time(seconds):
    """秒数をASS字幕形式の時間に変換 (h:mm:ss.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centiseconds = int((secs % 1) * 100)
    secs = int(secs)
    
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"

def timestamp_to_usec(timestamp: float) -> int:
    """秒単位のタイムスタンプをマイクロ秒に変換"""
    return int(float(timestamp) * 1_000_000)
