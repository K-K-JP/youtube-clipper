import yt_dlp
import os
import requests
from PIL import Image
import io
import subprocess
from datetime import datetime
from utility import sanitize_filename, extract_video_id

def get_video_metadata(video_url):
    """yt-dlpを使用して動画のメタデータを取得"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # 配信日時の処理
            upload_date = None
            upload_datetime = None
            weekday = None

            try:
                upload_datetime = datetime.strptime(info['upload_date'], '%Y%m%d')
                upload_date = upload_datetime.strftime('%Y-%m-%d')
                weekdays = ['月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日']
                weekday = weekdays[upload_datetime.weekday()]
            except ValueError:
                pass
            
            metadata = {
                'title': info.get('title', ''),
                'channel': info.get('channel', ''),
                'video_id': info.get('id', ''),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'upload_date': upload_date,
                'weekday': weekday,
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
            }
            
            return metadata
    except Exception as e:
        print(f"メタデータ取得エラー: {str(e)}")
        return {
            'title': 'Unknown',
            'channel': 'Unknown',
            'video_id': extract_video_id(video_url) or 'unknown',
            'duration': 0,
            'thumbnail': '',
            'upload_date': None,
            'weekday': None,
            'view_count': 0,
            'like_count': 0,
        }

def download_thumbnail(video_url, output_dir='backend/clips', channel_name='', filename_prefix=""):
    """動画のサムネイルをダウンロードして保存"""
    try:
        thumbnail_filename = "thumbnail.jpg"
        video_id = extract_video_id(video_url)

        print(f"元のchannel_name: {channel_name}")
        sanitized_name = sanitize_filename(channel_name)
        print(f"サニタイズ後: {sanitized_name}")

        if channel_name:
            channel_dir = os.path.join(output_dir, sanitized_name)
            video_specific_dir = os.path.join(channel_dir, video_id)
            
            if not os.path.exists(channel_dir):
                os.makedirs(channel_dir, exist_ok=True)
            if not os.path.exists(video_specific_dir):
                os.makedirs(video_specific_dir, exist_ok=True)
            
            thumbnail_path = os.path.join(video_specific_dir, thumbnail_filename)
        else:
            thumbnail_path = os.path.join(output_dir, thumbnail_filename)

        if os.path.exists(thumbnail_path):
            print(f"サムネイル既存のためスキップ: {thumbnail_path}")
            return thumbnail_path

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            thumbnail_url = None
            if 'thumbnails' in info and info['thumbnails']:
                thumbnails = sorted(info['thumbnails'], 
                                  key=lambda x: x.get('width', 0) * x.get('height', 0), 
                                  reverse=True)
                thumbnail_url = thumbnails[0]['url']
            
            if thumbnail_url:
                response = requests.get(thumbnail_url, timeout=30)
                response.raise_for_status()
                
                image = Image.open(io.BytesIO(response.content))
                image = image.convert('RGB')
                image.save(thumbnail_path, 'JPEG', quality=90)
                
                return thumbnail_path
                
    except Exception as e:
        print(f"サムネイルダウンロードエラー: {e}")
        return None

def download_live_chat_json(video_id: str) -> str:
    """yt-dlp を使ってライブチャットJSONをダウンロード"""
    output_dir = os.path.join("backend", "clips", "cache")
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{video_id}.live_chat.json")

    if os.path.exists(json_path):
        print(f"[yt-dlp] Live chat JSON は既に存在しています : {json_path}")
        return json_path

    output_template = os.path.join(output_dir, f"{video_id}.%(ext)s")

    command = [
        "yt-dlp",
        "--write-subs",
        "--sub-langs", "live_chat",
        "--skip-download",
        "-o", output_template,
        f"https://www.youtube.com/watch?v={video_id}"
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[yt-dlp] Error:\n{result.stderr}")
            return None

        if os.path.exists(json_path):
            print(f"[yt-dlp] Live chat JSON downloaded: {json_path}")
            return json_path
        else:
            print("[yt-dlp] JSON file not found after download.")
            return None

    except FileNotFoundError:
        print("yt-dlp is not installed or not in PATH.")
        return None

def download_partial_video(video_url, start_seconds, end_seconds, output_path, buffer_seconds=120):
    """YouTube動画の指定範囲のみをダウンロード"""
    try:
        actual_start = max(0, start_seconds - buffer_seconds)
        actual_end = end_seconds + buffer_seconds
    
        from datetime import timedelta
        start_hms = str(timedelta(seconds=actual_start))
        duration_seconds = actual_end - actual_start
        
        print(f"部分ダウンロード開始:")
        print(f"  開始時刻: {start_hms} ({actual_start}秒)")
        print(f"  継続時間: {duration_seconds}秒")
        print(f"  出力先: {output_path}")
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            'outtmpl': output_path,
            'quiet': False,
            'merge_output_format': 'mp4',
            'external_downloader': 'ffmpeg',
            'external_downloader_args': {
                'ffmpeg_i': ['-ss', start_hms, '-t', str(int(duration_seconds))]
            },
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        if os.path.exists(output_path):
            print(f"部分ダウンロード完了: {output_path}")
            return {
                'success': True,
                'actual_start': actual_start,
                'actual_end': actual_end,
                'path': output_path,
                'duration': duration_seconds
            }
        else:
            return {'success': False, 'error': 'ダウンロードファイルが見つかりません'}
            
    except Exception as e:
        print(f"部分ダウンロードエラー: {str(e)}")
        return {'success': False, 'error': str(e)}
