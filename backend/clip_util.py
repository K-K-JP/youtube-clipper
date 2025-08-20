import os
import re
import json
import math
import shutil
import tempfile
import subprocess
from pathlib import Path
import uuid
import threading
import time
import random
import traceback
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Optional, Union, Tuple
from datetime import timedelta

# === 外部ライブラリ ===
import pandas as pd
import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use('Agg')
from moviepy.editor import VideoFileClip
from natsort import natsorted


# === プロジェクト内モジュール ===
import config
# Sheets/translation
from transrate import translate_common
# Utility functions
from utility import (
    get_codec_info, sanitize_filename, extract_video_id, time_to_seconds, format_time, error_result, safe_float, safe_int
)
# File I/O
from file_io import (
    load_comments_from_cache, save_comments_to_cache, generate_chart_data_from_comments, generate_clip_urls_txt
)
# YouTube handling
from youtube_handler import get_video_metadata, download_thumbnail, download_partial_video
from comment_processor import get_comments, get_comments_for_timerange, calculate_max_comments_per_interval, select_comments_per_second
# Comment analysis (main scoring/period logic)
from analyze_comments import (
    analyze_comment_content, detect_excitement_periods, generate_clip_urls, analyze_excitement, analyze_custom_emojis,
    multi_stage_timewise_merge, merge_highlight_periods, smooth_scores, extract_top_windows, extract_best_subclip, ensure_top3_per_emotion
)
# Chart utilities
from chart_utils import generate_chart_data_from_comments
# Output generation
from output_generator import (
    generate_video_statistics_txt, generate_clip_comments_txt, generate_all_txt_files, save_per_second_scores, add_metadata_to_clips
)
from visualization import plot_excitement_graph, create_comment_heatmap, plot_comment_count_graph, concat_graphs_horizontal, create_vertical_score_graphs, plot_score_graph, plot_multi_score_graph, combine_graphs_to_canvas

# slide_graphs_to_video
from slide_graphs_to_video import add_sliding_graphs_to_video

# ASS utilities
from ass_utils import (
    create_ass_file, combine_video_and_ass, add_ass_subtitles_to_ed, create_ass_from_whisper, create_ass_file_9x16,create_ass_file_whisper
)

# Comment rendering/overlay
from comment_rendering import (
    extract_comments_around_time, create_thumbnail_overlay_image, CommentRenderer, VideoProcessor, ThumbnailCommentLaneManager, EmojiProcessor, CommentLaneManager, assign_comment_lanes_9x16, VideoProcessor9x16
)
# Emoji extraction/cache
from emoji_extractor import extract_custom_emojis_from_comments, process_emojis_from_full_chat, process_emojis_if_needed

# JSON export
from json_export import export_to_json
# Gemini prompt utilities
from gemini_prompt_util import save_gemini_prompt_and_data, parse_and_save_gemini_output, regenerate_gemini_prompt_and_data, parse_gemini_output, gemini_api_func
# Streamer summary export
from json_export_streamers import build_streamer_summary_from_results
# Create_clip_sheet
from create_clip_sheet import create_clip_sheet_from_process_video, set_combine_flag_true


def cut_clip_with_partial_download(
    video_url,
    start_time,
    end_time,
    rank=None,
    score_percent=None,
    output_dir='clips',
    channel_name=None,
    main_label=None,
    subtitle_data=None,  # ASS字幕用データ（リスト）
    clip_index=None,  # combine_orderでの順番（0始まり）
    draw_comments=None,  # 追加: クリップごとのコメントリスト
    whisper_subtitles=None # 追加: Whisper字幕データ（リスト）
):
    """
    部分ダウンロードを使用した効率的なクリップ作成
    
    Parameters:
    - video_url: YouTube動画のURL
    - start_time: クリップ開始時間（秒）
    - end_time: クリップ終了時間（秒）
    - rank: 順位
    - score_percent: スコア（パーセント）
    - output_dir: 出力ディレクトリ
    - comments: コメントリスト
    - buffer_minutes: 前後のバッファ時間（分）
    - subtitle_data: ASS字幕用データ（リスト、各要素は{'text', 'start', 'end'}）
    - whisper_subtitles: Whisper字幕用データ（リスト、各要素は{'text', 'start', 'end'}）
    """

    try:
        # クリップ抽出失敗時もclips: []を返すためのエラーハンドリング用
        def error_result(message, extra=None):
            result = {
                'clips': [],
                'error': message
            }
            if extra:
                result.update(extra)
            return result
        # 最初に絶対パスを確定（作業ディレクトリ変更前）
        output_dir = os.path.abspath(output_dir)
        
        # 基本情報を取得
        video_id = extract_video_id(video_url)
        if not video_id:
            return error_result("無効な動画URLです")
        metadata = get_video_metadata(video_url)
        channel_name = metadata.get('channel', '')

        if channel_name:
            # 新しいフォルダ構造: clips/{チャンネル名}/
            channel_dir = os.path.join(output_dir, sanitize_filename(channel_name))
            video_specific_dir = os.path.join(channel_dir, video_id)
            if not os.path.exists(channel_dir):
                os.makedirs(channel_dir, exist_ok=True)
        else:
            video_specific_dir = os.path.join(output_dir, video_id)

        print(f"video_specific_dir: {video_specific_dir}")
        if not os.path.exists(video_specific_dir):
            os.makedirs(video_specific_dir, exist_ok=True)

        # OP用一時動画保存先ディレクトリ
        tmp_dir = os.path.join('backend', 'clips', 'tmp', video_id)
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir, exist_ok=True)

        # 時間変換（エラーハンドリング強化）
        try:
            if isinstance(start_time, str):
                start_seconds = time_to_seconds(start_time)
            else:
                start_seconds = float(start_time)

            if isinstance(end_time, str):
                end_seconds = time_to_seconds(end_time)
            else:
                end_seconds = float(end_time)

            if start_seconds < 0 or end_seconds < 0:
                return error_result("開始時間と終了時間は0以上である必要があります")
            if start_seconds >= end_seconds:
                return error_result("開始時間は終了時間より前である必要があります")
            print(f"時間変換完了: {start_seconds}s - {end_seconds}s")
        except Exception as e:
            return error_result(f"時間変換エラー: {str(e)}. start_time={start_time}, end_time={end_time}")

        # 一時ディレクトリを作成（従来通り）
        temp_dir = tempfile.mkdtemp()
        print(f"一時ディレクトリ: {temp_dir}")

        # クリップID生成
        clip_id = f"{video_id}_{clip_index if clip_index is not None else '0'}"

        # パス生成
        ass_path = os.path.join(tmp_dir, f"{clip_id}_whisper.ass")
        output_whispered_path = os.path.join(tmp_dir, f"{clip_id}_whispered.mp4")
        for_short_whispered_path = os.path.join(tmp_dir, f"{rank}_whispered_short.mp4")

        # whisper_subtitlesが指定されている場合はそれを使用
        if not whisper_subtitles:
            print("Whisper字幕なし: 部分ダウンロードを実行します")
            # 部分ダウンロード実行
            buffer_seconds = 0
            temp_video_path = os.path.join(temp_dir, f"{video_id}_partial.mp4")
            download_result = download_partial_video(
                video_url,
                start_seconds,
                end_seconds,
                temp_video_path,
                buffer_seconds
            )
            if not download_result['success']:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                return error_result(f"部分ダウンロード失敗: {download_result.get('error')}")
        else:
            temp_video_path=os.path.join(tmp_dir, f"{video_id}_clip_{rank}.mp4")
            # download_resultを初期化
            download_result = {
                'success': True,
                'actual_start': start_seconds,
                'actual_end': end_seconds,
                'path': temp_video_path
            }


        # creator_styles.jsonから縁取り色取得
        styles_path = Path('backend') / 'data' / 'creator_styles.json'
        outline_color = '&H00000000'
        if channel_name:
            try:
                with open(styles_path, encoding='utf-8') as f:
                    styles = json.load(f)
                outline_color = styles.get(sanitize_filename(channel_name), {}).get('outline_color', outline_color)
            except Exception as e:
                print(f"[WARN] creator_styles.json読み込み失敗: {e}")

        subtitle_style = {
            "font_name": "ラノベPOP v2",
            "font_size": 120,
            "font_color": "&H00FFFFFF",
            "outline_color": outline_color,
            "align": 2,
        }


        try:
            if not whisper_subtitles:
                # subs_infoが空: 従来通りwhisper字幕生成
                create_ass_from_whisper(temp_video_path, ass_path, subtitle_style, language="ja")
            else:
                # whisper_subtitlesがある場合: subs_infoをASS形式に変換
                subs_ass_lines = []
                for seg in whisper_subtitles:
                    subs_ass_lines.append({
                        'text': seg.get('text', ''),
                        'start': seg.get('start', 0),
                        'end': seg.get('end', 0),
                        'font_name': subtitle_style.get('font_name', 'ラノベPOP v2'),
                        'font_size': subtitle_style.get('font_size', 120),
                        'font_color': subtitle_style.get('font_color', '&H00FFFFFF'),
                        'outline_color': subtitle_style.get('outline_color', '&H00000000'),
                        'align': subtitle_style.get('align', 2)
                    })
                create_ass_file_whisper(subs_ass_lines, ass_path, creator_name=channel_name)
            combine_video_and_ass(temp_video_path, ass_path, output_whispered_path)
            print(f"Whisper字幕生成・合成完了: {output_whispered_path}")
        except Exception as e:
            print(f"[ERROR] Whisper字幕生成・合成失敗: {e}")
            import traceback
            traceback.print_exc()


        # backend/clips/tmp/{動画ID}/ にもコピー保存
        op_video_path = os.path.join(tmp_dir, f"{video_id}_partial_{clip_index if clip_index is not None else '0'}.mp4")
        shutil.copy2(temp_video_path, op_video_path)
        shutil.copy2(output_whispered_path, for_short_whispered_path)


        # original_file_pathはtmp_dirの方を返す
        original_file_path_for_response = op_video_path

        # 時間オフセット計算
        actual_video_start = start_seconds - download_result['actual_start']
        
        
        # ファイル名生成
        unique_id = str(uuid.uuid4())[:8]
        score_text = f"_{score_percent}%" if score_percent is not None else ""
        rank_prefix = f"{rank}位_" if rank is not None else ""
        label_prefix = f"{main_label}_" if main_label else ""
        start_simple = format_time(start_seconds)
        output_filename = f"{label_prefix}{rank_prefix}{start_simple}{score_text}_{unique_id}.mp4"
        output_filename = sanitize_filename(output_filename)
        output_path = os.path.join(video_specific_dir, output_filename)
        

        # 2. コメント取得とフィルタ
        if draw_comments is not None:
            # すでにrank/clip_idで抽出済みのコメントを使う
            clip_comments = draw_comments.copy()
            # timestamp補正（start_seconds基準に）
            for c in clip_comments:
                if 'timestamp' in c:
                    c['timestamp'] = float(c['timestamp']) - start_seconds
        else:
            comments = load_comments_from_cache(video_url)
            if comments is None:
                comments = get_comments(video_url)
            clip_start = download_result['actual_start']
            clip_end = download_result['actual_end']
            clip_comments = [c for c in comments if start_seconds <= c['timestamp'] <= clip_end]
            for c in clip_comments:
                c['timestamp'] -= start_seconds

        if not clip_comments:
            print("コメントが見つかりませんでした。オーバーレイをスキップします。")
            return error_result("コメントが見つかりませんでした。オーバーレイをスキップします。")

        # 既存の絵文字辞書をロード
        print("✓ 既存の絵文字辞書処理に入りました")
        emoji_dict_path = os.path.join("backend", "clips", "emoji_dict", f"{sanitize_filename(channel_name)}_emoji.json")
        try:
            with open(emoji_dict_path, 'r', encoding='utf-8') as f:
                emoji_dict = json.load(f)
        except:
            emoji_dict = {}
        

        # 3. 絵文字処理とレーン割り当て
        print("✓ 絵文字処理とレーン割り当て処理に入りました")
        emoji_processor = EmojiProcessor(cache_base_dir=Path(__file__).parent / "emoji_cache")
        emoji_cache = emoji_processor.download_and_cache_emojis(emoji_dict or {}, channel_name or "default")

        # emoji_cache に original 画像を追加する
        sanitized_channel = sanitize_filename(channel_name or "default")
        cache_dir = Path(__file__).parent / "emoji_cache" / sanitized_channel
        for emoji_id, info in emoji_cache.items():
            path = info.get("path")
            if not path:
                continue
            full_path = cache_dir / path
            if full_path.exists():
                try:
                    emoji_cache[emoji_id]["original"] = Image.open(full_path).convert("RGBA")
                except Exception as e:
                    print(f"[読み込み失敗] {emoji_id}: {e}")

        # 4. オーバーレイフレームの生成
        print("✓ オーバーレイフレームの生成処理に入りました")
        with VideoFileClip(download_result['path']) as clip_video:
            fps = 30
            duration = end_seconds - start_seconds
            width, height = clip_video.size
            frame_output_dir = os.path.join(os.path.dirname(output_path), "overlay_frames",f"{rank}")
            os.makedirs(frame_output_dir, exist_ok=True)
            # ✅ 既存チェック（最初のフレームが存在する場合スキップ）
            sample_frame_path = os.path.join(frame_output_dir, "000000.png")
            if os.path.exists(sample_frame_path):
                print(f"✓ フレーム画像が既に存在するためスキップ: {frame_output_dir}")
            else:
                font_path = r"C:\Windows\Fonts\meiryo.ttc"
                font_size = 36
                # 10レーンで上540pxに収める
                desired_lane_height = 54  # 540/10=54
                renderer = CommentRenderer(font_path=font_path, font_size=font_size, lane_height=desired_lane_height)
                # 絵文字分解・total_width 計算
                for c in clip_comments:
                    c['elements'] = emoji_processor.parse_comment_elements(c['text'], emoji_dict)
                    c['total_width'] = sum([
                        renderer.font.getbbox(el['content'])[2] - renderer.font.getbbox(el['content'])[0]
                        if el['type'] == 'text'
                        else renderer.emoji_size[0]
                        for el in c['elements']
                    ])
                # レーン割り当て（必要なら）
                from comment_rendering import CommentLaneManager
                if not all('lane' in c for c in clip_comments):
                    lane_manager = CommentLaneManager(max_lanes=10)
                    clip_comments = lane_manager.assign_comment_lanes(clip_comments)
                # 並列フレーム生成
                video_processor = VideoProcessor(temp_dir=frame_output_dir)
                frame_count = int(duration * fps)
                success = video_processor._generate_frame_images(
                    comments=clip_comments,
                    emoji_cache=emoji_cache,
                    frame_count=frame_count,
                    fps=fps
                )
                if not success:
                    return error_result("フレーム画像の生成に失敗しました")

        # GPU使用可否をチェック
        gpu_available = False
        try:
            test_cmd = ['ffmpeg', '-hwaccels']
            test_result = subprocess.run(test_cmd, capture_output=True, text=True)
            if 'cuda' in test_result.stdout or 'nvenc' in test_result.stdout:
                gpu_available = True
        except:
            pass
        
        print(f"GPU エンコーダー使用可能: {gpu_available}")

        # 5. FFmpegで動画と合成
        if len(clip_comments) > 0:
            print("✓ コメント付き処理に入りました")
            
            # コメント付きバージョンのファイル名
        comment_output_filename = f"{label_prefix}{rank_prefix}{start_simple}{score_text}_commented_{unique_id}.mp4"
        comment_output_filename = sanitize_filename(comment_output_filename)
        comment_output_path = os.path.join(video_specific_dir, comment_output_filename)
            
        try:
            # プロセス固有の識別子を生成
            process_id = f"{threading.get_ident()}_{int(time.time())}"
            

            # ★★★ 詳細なデバッグ情報を追加 ★★★
            print(f"=== 字幕処理デバッグ情報 ===")
            print(f"現在のディレクトリ: {os.getcwd()}")
            
            
            # ステップ1: 動画を切り出し（字幕なし）
            print("ステップ1: 動画を切り出し中...")
            process_id = f"{threading.get_ident()}_{int(time.time())}"
            temp_cut_video = os.path.join(temp_dir, f'temp_cut_{process_id}.mp4')
            ass_file_path = os.path.join(temp_dir, 'comments.ass')
            
            cmd1 = [
                'ffmpeg',
                '-loglevel', 'error',
                '-i', output_whispered_path,
                '-ss', str(actual_video_start),  # キーフレーム調整前の時間
                '-t', str(end_seconds - start_seconds),  # 継続時間で指定
                '-c:v', 'h264_nvenc' if gpu_available else 'libx264',
                '-preset', 'fast' if not gpu_available else 'p4', 
                '-r', '30',
                '-g', '120',
                '-c:a', 'copy',
                '-avoid_negative_ts', 'make_zero',
                '-y',
                temp_cut_video
            ]
            result1 = subprocess.run(cmd1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
            if result1.returncode != 0:
                print(f"ステップ1エラー: {result1.stderr}")
                return error_result(f"動画切り出しエラー: {result1.stderr}")
            print("ステップ1完了: 動画の切り出し成功")
        finally:

                pass
        
        # ASS追加前の一時動画は clips/tmp/{動画ID}.mp4 で保存
        tmp_dir = os.path.join('backend', 'clips', 'tmp')
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir, exist_ok=True)
        sanitized_video_id = sanitize_filename(video_id)
        idx_str = str(clip_index) if clip_index is not None else '0'
        output_abs_path = os.path.join(tmp_dir, sanitized_video_id, f"{idx_str}.mp4")
        os.makedirs(os.path.dirname(output_abs_path), exist_ok=True)
        output_abs_path = os.path.abspath(output_abs_path)

        print(f"ASS追加前の一時動画: {output_abs_path}")

        # ASS合成後の一時ファイル
        ass_output_abs_path = os.path.join(tmp_dir, sanitized_video_id, f"{idx_str}_ass.mp4")
        ass_output_abs_path = os.path.abspath(ass_output_abs_path)

        # フェード時間を設定（秒）
        fade_duration = 1.0  # 1000ms
        fade_out_start = end_seconds - start_seconds - fade_duration - 0.05


        cmd2 = [
            "ffmpeg", "-y",
            "-loglevel", "error",
            "-i", temp_cut_video,
            "-framerate", "30",
            "-start_number", "0",
            "-i", os.path.join(frame_output_dir, "%06d.png"),
            "-filter_complex",
            f"[0:v][1:v] overlay=0:0:format=auto [overlaid]; "
            f"[overlaid] fade=in:0:{int(fade_duration*30)},fade=out:{int((end_seconds-start_seconds-fade_duration)*30)}:{int(fade_duration*30)} [video_faded]",
            "-r", "30",
            "-map", "[video_faded]",
            "-map", "0:a",
            "-filter:a", f"afade=in:st=0:d={fade_duration},afade=out:st={fade_out_start}:d={fade_duration}",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-c:a", "aac",
            output_abs_path
        ]
        try:
            subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
            print(f"オーバーレイ合成完了: {output_abs_path}")
            download_result['path'] = output_abs_path
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg合成に失敗: {e}")
            return error_result(f"FFmpeg合成に失敗: {e}")
        # 一時ディレクトリ削除
        shutil.rmtree(temp_dir)
        
        output_path_for_response = comment_output_path
        filename_for_response = comment_output_filename
        
        # === ASS字幕生成・合成 ===
        # クリップごとにASS字幕を生成し、動画に合成する
        # subtitle_dataが指定されていればそれを使い、なければ従来通りタイトル＋順位のみ
        if subtitle_data is None:
            subtitle_data = [{
                'text': f"{metadata.get('title', '')} ({rank}位)",
                'start': 0,
                'end': end_seconds - start_seconds
            }]
        # ASSファイルの出力先を /backend/clips/ASS/{動画ID}.ass に統一
        sanitized_video_id = sanitize_filename(video_id)
        idx_str = str(clip_index) if clip_index is not None else '0'
        ass_dir = os.path.join('backend', 'clips', 'tmp', sanitized_video_id)
        if not os.path.exists(ass_dir):
            os.makedirs(ass_dir)
        ass_path = os.path.join(ass_dir, f"{idx_str}.ass")
        # 出力ファイル名もsanitize
        output_filename = sanitize_filename(output_filename)
        output_path = os.path.join(video_specific_dir, output_filename)
        try:
            create_ass_file(subtitle_data, ass_path, creator_name=channel_name)
            print(f"ASS字幕ファイル生成: {ass_path}")
            # 合成先ファイル名
            ass_output_filename = sanitize_filename(f"{label_prefix}{rank_prefix}{start_simple}{score_text}_ass_{unique_id}.mp4")
            ass_output_path = os.path.join(video_specific_dir, ass_output_filename)
            # ASS合成は clips/tmp/{動画ID}.mp4 → video_specific_dir/ASS付きファイル で行う
            combine_video_and_ass(output_abs_path, ass_path, ass_output_abs_path)
            print(f"ASS字幕合成完了: {ass_output_abs_path}")
            print("[INFO] ASS字幕合成後の後続処理を開始します... (ファイルコピーや結合などがあればここで進行)")
            output_path_for_response = ass_output_abs_path
            filename_for_response = os.path.basename(ass_output_abs_path)
            # 生成したASSファイルのパスもレスポンスに含める（デバッグ/検証用）
            # returnに含めたい場合は下記を有効化
            # output_ass_path = ass_path
        except Exception as e:
            print(f"ASS字幕生成・合成エラー: {e}")
            # 失敗時は元の動画を返す
            output_path_for_response = output_abs_path
            filename_for_response = os.path.basename(output_abs_path)

        return {
            "success": True,
            "file_path": output_path_for_response,
            "filename": filename_for_response,
            "original_file_path": original_file_path_for_response,  # OP用はtmp_dirのパスを返す
            "start_time": start_seconds,
            "end_time": end_seconds,
            "duration": end_seconds - start_seconds,
            "video_id": video_id,
            "title": metadata['title'],
            "channel": metadata['channel'],
            "applied_rank": rank,
            "resolution": "1080p",
            "encoder": "libx264",
            "comment_count": len(clip_comments),
            "download_info": {
                "partial_range": f"{download_result['actual_start']:.1f}s - {download_result['actual_end']:.1f}s",
                "saved_time": f"約{(download_result['actual_end'] - download_result['actual_start'])/60:.1f}分のダウンロード"
            }
        }
    except Exception as e:
        print(f"処理中にエラーが発生: {str(e)}")
        print(f"エラー詳細: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        # エラー時の一時ディレクトリクリーンアップ
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
        return error_result(f"処理中にエラーが発生しました: {str(e)}")

# === クリップ生成＋ASS字幕合成のみ ===
def generate_clips_with_ass(
    video_url,
    group_id="hololive",
    combine_order=None
):
    """
    指定クリップリスト（combine_order）に従い、各クリップの切り出し・ASS字幕合成までを行う。
    結合は行わず、生成されたクリップ（ASS付きmp4）のパスリストを返す。
    """
    try:
        metadata = get_video_metadata(video_url)
        channel_name = metadata.get('channel', '')
        video_id = extract_video_id(video_url)
        sanitized_channel = sanitize_filename(channel_name)
        # clip_dir = os.path.join('backend', "clips", sanitized_channel, video_id)
        if combine_order is None:
            raise ValueError("combine_orderは必須です")
        video_paths = []
        original_video_paths = []
        combined_clip_metadata = []
        # コメントキャッシュを取得
        comments = load_comments_from_cache(video_url)
        if comments is None:
            comments = get_comments(video_url)

        # draw_commentsのロード（ファイルパスは combine_clips_with_overlay_and_subs から渡す場合は引数で受け取る形に拡張可）
        draw_comments_path = os.path.join('backend', 'data', 'draw_comments', f"{video_id}.json")
        draw_comments = None
        if os.path.exists(draw_comments_path):
            with open(draw_comments_path, 'r', encoding='utf-8') as f:
                import json
                draw_comments = json.load(f)

        for idx, clip in enumerate(combine_order):
            laugh_score = clip.get('laugh_score')
            healing_score = clip.get('healing_score')
            chaos_score = clip.get('chaos_score')
            user_comment = clip.get('comment', '')
            group_id = clip.get('group_id', group_id)
            # クリップ区間内のコメント数を計算
            start_sec = clip.get('start_sec', 0)
            end_sec = clip.get('end_sec', 0)
            comment_count = len([cm for cm in comments if start_sec <= cm.get('timestamp', 0) <= end_sec])
            duration = int(end_sec - start_sec)
            subtitle_lines = []
            styles_path = Path('backend') / 'data' / 'creator_styles.json'
            creator_name = sanitize_filename(channel_name) if channel_name else 'デフォルト'
            style = {
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00FFD288",
                "font_name": "ラノベPOP v2"
            }
            if styles_path.exists():
                with open(styles_path, 'r', encoding='utf-8') as f:
                    all_styles = json.load(f)
            else:
                all_styles = {}
            style.update(all_styles.get("デフォルト", {}))
            if creator_name in all_styles:
                style.update(all_styles.get(creator_name, {}))
            else:
                # スタイルがなければコマンドラインからoutline_colorを入力
                print(f"\nクリエイター『{creator_name}』のoutline_colorを16進数ASS色コードで入力してください（例: &H00FFD288）:")
                outline_color = input().strip()
                if outline_color:
                    style["outline_color"] = outline_color
                    all_styles[creator_name] = {"outline_color": outline_color}
                    # ファイルに追記保存
                    styles_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(styles_path, 'w', encoding='utf-8') as f:
                        json.dump(all_styles, f, ensure_ascii=False, indent=2)
            if user_comment:
                if user_comment:
                    subtitle_lines.append({
                        'text': '{\\fad(1000,1000)}' + user_comment,
                        'start': 0,
                        'end': min(15, duration),
                        'font_size': 132,
                        'pos': '10,10',
                        'align': 7,
                        'font_color': style.get('font_color', '&H00FFFFFF'),
                        'outline_color': '&H00333333',
                        'font_name': 'ラノベPOP v2'
                    })
            # 横並び・色分けで1行にまとめて表示（ASSインラインタグ利用）
            if group_id == "hololive_en":
                score_text = (
                    '{\\fad(1000,1000)}'
                    '{\\pos(20,130)}{\\c&H00FFFF&}Laugh Meter：'
                    '{\\pos(120,130)}{\\c&HFFFFFF&}' + str(laugh_score) +
                    '{\\pos(320,130)}{\\c&H00FFAA00&}　Cuteness Meter：'
                    '{\\pos(440,130)}{\\c&HFFFFFF&}' + str(healing_score) +
                    '{\\pos(640,130)}{\\c&HFF80FF&}　Hype Level：'
                    '{\\pos(800,130)}{\\c&HFFFFFF&}' + str(chaos_score)
                )
            else:
                score_text = (
                    '{\\fad(1000,1000)}'
                    '{\\pos(20,130)}{\\c&H00FFFF&}爆笑指数：'
                    '{\\pos(120,130)}{\\c&HFFFFFF&}' + str(laugh_score) +
                    '{\\pos(320,130)}{\\c&H00FFAA00&}　かわいさ指数：'
                    '{\\pos(440,130)}{\\c&HFFFFFF&}' + str(healing_score) +
                    '{\\pos(640,130)}{\\c&HFF80FF&}　盛り上がり指数：'
                    '{\\pos(800,130)}{\\c&HFFFFFF&}' + str(chaos_score)
                )
            subtitle_lines.append({
                'text': score_text,
                'start': 3,
                'end': min(15, duration),
                'font_size': 62,
                'pos': None,  # インラインタグでpos指定
                'align': 7,
                'font_color': style.get('font_color', '&H00FFFFFF'),
                'outline_color': '&H00333333',
                'font_name': 'ラノベPOP v2'
            })
            if group_id == "hololive_en":
                subtitle_lines.append({
                    'text': '{\\fad(1000,1000)}' + f"{comment_count}comments / {duration}sec",
                    'start': 3,
                    'end': min(15, duration),
                    'font_size': 62,
                    'pos': '20,200',
                    'align': 7,
                    'font_color': style.get('font_color', '&H00FFFFFF'),
                    'outline_color': '&H00333333',
                    'font_name': 'ラノベPOP v2'
                })
            else:
                subtitle_lines.append({
                    'text': '{\\fad(1000,1000)}' + f"{comment_count}コメント / {duration}秒",
                    'start': 3,
                    'end': min(15, duration),
                    'font_size': 62,
                    'pos': '20,200',
                    'align': 7,
                    'font_color': style.get('font_color', '&H00FFFFFF'),
                    'outline_color': '&H00333333',
                    'font_name': 'ラノベPOP v2'
                })

            # draw_commentsからrankまたはclip_idが一致するコメントのみ抽出
            clip_rank = clip.get('rank')
            clip_id = clip.get('clip_id')
            filtered_draw_comments = []
            if draw_comments is not None:
                if clip_id is not None:
                    filtered_draw_comments = [c for c in draw_comments if c.get('clip_id') == clip_id]
                elif clip_rank is not None:
                    filtered_draw_comments = [c for c in draw_comments if c.get('clip_rank') == clip_rank]
            # subs_infoからクリップランクに該当する字幕情報を抽出
            subs_info = clip.get('subs_info', [])
            filtered_subs_info = [s for s in subs_info if s.get('rank') == clip_rank]

            result = cut_clip_with_partial_download(
                video_url=video_url,
                start_time=start_sec,
                end_time=end_sec,
                rank=clip.get('rank'),
                main_label=clip.get('main_label'),
                channel_name=channel_name,
                output_dir=os.path.join('backend', 'clips'),
                subtitle_data=subtitle_lines,
                clip_index=idx,
                draw_comments=filtered_draw_comments if filtered_draw_comments else None,
                whisper_subtitles=filtered_subs_info if filtered_subs_info else None
            )
            if not result.get('success'):
                print(f"[ERROR] クリップ生成失敗: {result.get('error')}")
                return None
            if not os.path.exists(result['file_path']):
                print(f"[ERROR] クリップファイルが存在しません: {result['file_path']}")
                return None
            video_paths.append(result['file_path'])
            original_video_paths.append(result.get('original_file_path'))
            combined_clip_metadata.append({
                'file_path': result['file_path'],
                'original_file_path': result.get('original_file_path'),
                'start_sec': clip['start_sec'],
                'end_sec': clip['end_sec'],
                'rank': clip.get('rank'),
                'main_label': clip.get('main_label'),
                'comment': user_comment,  # 一言コメントを追加
                '爆笑指数': laugh_score,
                'かわいさ指数': healing_score,
                '盛り上がり指数': chaos_score
            })
        return {
            'success': True,
            'clip_paths': video_paths,
            'clip_metadata': combined_clip_metadata,
            'original_video_paths': original_video_paths
        }
    except Exception as e:
        print(f"[ERROR] generate_clips_with_assで例外発生: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'clip_paths': [],
            'clip_metadata': [],
            'error': str(e)
        }

# === クリップ結合のみ ===
def concat_clips_with_eyecatch(
    video_paths,
    channel_name,
    video_id,
    group_id="hololive",
    output_filename=None,
    clip_metadata=None,
    op_temp_path=None
):
    """
    既に生成済みのクリップ動画リスト（video_paths）を、OP/アイキャッチ/ED込みで指定順に結合する。
    clip_metadata: 各クリップのスコア情報リスト（dictのリスト）
    """
    sanitized_channel = sanitize_filename(channel_name)
    if group_id == "hololive":
        eyecatch_dir_name = config.HOLOLIVE_EYECATCH_DIR
    elif group_id == "nijisanji":
        eyecatch_dir_name = config.NIJISANJI_EYECATCH_DIR
    elif group_id == "hololive_en":
        eyecatch_dir_name = config.HOLOLIVE_EN_EYECATCH_DIR
    else:
        raise ValueError(f"Invalid group_id: {group_id}")
    clip_dir = os.path.join('g:/マイドライブ/clips', sanitized_channel, video_id)
    if not os.path.exists(clip_dir):
        os.makedirs(clip_dir, exist_ok=True)
    eyecatch_dir = os.path.join('backend', eyecatch_dir_name)
    op_path = op_temp_path
    summary_streamers_path = os.path.join(os.path.dirname(__file__), 'data', 'summary_streamers.json')
    # summary_streamers.jsonからcreator_engを取得し、なければsanitized_channelを使う
    creator_eng = None
    if os.path.exists(summary_streamers_path):
        with open(summary_streamers_path, 'r', encoding='utf-8') as f:
            streamer_db = json.load(f)
        if channel_name in streamer_db:
            creator_eng = streamer_db[channel_name].get('creator_eng', None)
    if creator_eng:
        ending_path = os.path.join(eyecatch_dir, f"{creator_eng}.mp4")
    else:
        ending_path = os.path.join(eyecatch_dir, f"{sanitized_channel}.mp4")
    eyecatches = sorted([os.path.join(eyecatch_dir, f) for f in os.listdir(eyecatch_dir) if f.startswith("アイキャッチ")])
    selected_eyecatches = eyecatches[:3]
    # ランダムに2つ選ぶ（順序もランダム）
    if len(selected_eyecatches) >= 2:
        random_eyecatches = random.sample(selected_eyecatches, 2)
    else:
        random_eyecatches = selected_eyecatches
    # 結合順を構築
    n = len(video_paths)
    concat_list = [op_path]
    # print(f"[DEBUG] OP path: {op_path}")
    # print(f"[DEBUG] video_paths: {video_paths}")
    # print(f"[DEBUG] selected_eyecatches: {selected_eyecatches}")
    if n <= 3:
        # OPの直後のアイキャッチを入れない
        concat_list.extend(video_paths)
    elif n <= 6:
        # ランダムに選んだ2つのうち1つ目を途中で挿入
        concat_list.extend(video_paths[:3])
        concat_list.append(random_eyecatches[0])
        concat_list.extend(video_paths[3:])
    elif n == 7:
        # 7個の時は6と7の間に2つ目を挿入
        concat_list.extend(video_paths[:3])
        concat_list.append(random_eyecatches[0])
        concat_list.extend(video_paths[3:6])
        concat_list.append(random_eyecatches[1])
        concat_list.extend(video_paths[6:])
    else:
        # ランダムに選んだ2つを途中で2回挿入（8個以上）
        concat_list.extend(video_paths[:3])
        concat_list.append(random_eyecatches[0])
        concat_list.extend(video_paths[3:7])
        concat_list.append(random_eyecatches[1])
        concat_list.extend(video_paths[7:])
    # print(f"[DEBUG] concat_list: {concat_list}")
    for p in concat_list:
        # print(f"[DEBUG] concat_list file exists: {p} -> {os.path.exists(p)}")
        if not os.path.exists(p):
            print(f"[ERROR] ファイルが存在しません: {p}")

    # --- ED字幕付き動画を生成 ---
    # summary_videos.json から統計値を取得
    print("[DEBUG] ED字幕付き動画を生成")
    archive_time = ""
    total_comments = 0
    max_comments_10s = 0
    avg_comments_1h = 0
    summary_videos_path = os.path.join(os.path.dirname(__file__), 'data', 'summary_videos.json')
    # print(f"[DEBUG] summary_videos_path: {summary_videos_path}")
    if os.path.exists(summary_videos_path):
        with open(summary_videos_path, 'r', encoding='utf-8') as f:
            summary_db = json.load(f)
        video_summary = summary_db.get(video_id, None)
        # print(f"[DEBUG] video_summary: {video_summary}")
        # video_summaryが存在する場合は統計値を取得
        if video_summary:
            # duration_minutes → archive_time (hh:mm:ss)
            duration_minutes = video_summary.get('duration_minutes', 0)
            duration_seconds = int(duration_minutes * 60)
            archive_time = str(timedelta(seconds=duration_seconds))
            total_comments = video_summary.get('total_comments', 0)
            max_comments_10s = video_summary.get('max_comments_10sec', 0)
            # avg_comments_per_minute → 1時間あたり
            avg_per_min = video_summary.get('avg_comments_per_minute', 0)
            avg_comments_1h = int(avg_per_min * 60)  # 1時間=60分
            # print(f"[DEBUG] archive_time: {archive_time}, total_comments: {total_comments}, max_comments_10s: {max_comments_10s}, avg_comments_1h: {avg_comments_1h}")
        else:
            print(f"[WARN] summary_videos.jsonにvideo_id {video_id} のデータがありません")
    else:
        print(f"[WARN] summary_videos.jsonが見つかりません: {summary_videos_path}")

    # ASS付きED動画の一時パス
    # ED_with_subs.mp4を backend/clips/tmp/{動画ID}/ に出力
    tmp_dir = os.path.join('backend', 'clips', 'tmp', video_id)
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
    # print(f"[DEBUG] 一時ディレクトリ: {tmp_dir}")
    ed_with_ass_path = os.path.join(tmp_dir, 'ED_with_subs.mp4')
    print(f"[DEBUG] add_ass_subtitles_to_ed呼び出し直前: ed_video_path={ending_path}, output_path={ed_with_ass_path}, archive_time={archive_time}, total_comments={total_comments}, max_comments_10s={max_comments_10s}, avg_comments_1h={avg_comments_1h}")
    add_ass_subtitles_to_ed(
        ed_video_path=ending_path,
        output_path=ed_with_ass_path,
        archive_time=archive_time,
        total_comments=total_comments,
        max_comments_10s=max_comments_10s,
        avg_comments_1h=avg_comments_1h
    )
    print(f"[DEBUG] add_ass_subtitles_to_ed呼び出し直後")
    concat_list.append(ed_with_ass_path)
    # FFmpeg結合
    input_args = []
    for path in concat_list:
        input_args.extend(["-i", path])
    # print(f"[DEBUG] input_args: {input_args}")
    inputs = "".join([f"[{i}:v][{i}:a]" for i in range(len(concat_list))])
    filter_complex = f"{inputs}concat=n={len(concat_list)}:v=1:a=1[outv][outa]"
    # print(f"[DEBUG] filter_complex: {filter_complex}")
    if output_filename is None:
        unique_id = str(uuid.uuid4())[:8]
        output_filename = f"combined_{video_id}_{unique_id}.mp4"
    output_video = os.path.join(clip_dir, output_filename)
    # print(f"[DEBUG] output_filename: {output_filename}")
    # print(f"[DEBUG] output_video: {output_video}")
    try:
        print("[DEBUG] reached before ffmpeg command")
        cmd = ["ffmpeg", "-loglevel", "error"] + input_args + [
            "-filter_complex", filter_complex,
            "-loglevel", "error", 
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            output_video
        ]
        # print(f"[DEBUG] concat_clips_with_eyecatch FFmpegコマンド: {' '.join(cmd)}")
        # ffmpegの標準出力・標準エラーをリアルタイムで表示
        process = subprocess.Popen(cmd, stdout=None, stderr=None)
        returncode = process.wait()
        if returncode != 0:
            print(f"[ERROR] concat_clips_with_eyecatch FFmpeg結合失敗: returncode={returncode}")
            for p in concat_list:
                print(f"[ERROR] concat_list file exists: {p} -> {os.path.exists(p)}")
            print(f"[ERROR] input_args: {input_args}")
            print(f"[ERROR] filter_complex: {filter_complex}")
            print(f"[ERROR] output_filename: {output_filename}")
            print(f"[ERROR] output_video: {output_video}")
            return None
        print(f"✅ concat_clips_with_eyecatch: 動画を結合しました: {output_video}")
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        traceback.print_exc()
        return None

    # --- 概要欄.txt 出力 ---
    OP_DURATION = 11.000
    EYECATCH_1_DURATION = 3.000
    EYECATCH_2_DURATION = 3.133
    EYECATCH_3_DURATION = 3.000
    ED_DURATION = 15.033
    twitter_url="https://x.com/comment_holo"
    # メタデータ取得
    try:
        metadata = get_video_metadata(f"https://www.youtube.com/watch?v={video_id}")
        video_title = metadata.get('title', '')
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        video_title = ''
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    
    # タイムスタンプ計算
    timestamps = []
    cur = 0.0
    timestamps.append((cur, 'Opening' if group_id == "hololive_en" else 'オープニング'))
    cur += OP_DURATION
    eyecatch_durations = [EYECATCH_1_DURATION, EYECATCH_2_DURATION, EYECATCH_3_DURATION]
    eyecatch_insert_points = []
    if n <= 3:
        eyecatch_insert_points = []  # OP直後にアイキャッチを入れない
    elif n <= 6:
        eyecatch_insert_points = [3]
    else:
        eyecatch_insert_points = [3, 6]
    eyecatch_idx = 0
    def format_comment(meta):
        # clip_metadataの 'comment' キーを使う
        return meta.get('comment', '')
    if not clip_metadata or len(clip_metadata) != n:
        clip_metadata = [{} for _ in range(n)]
    for i in range(n):
        # アイキャッチの直後なら加算
        if eyecatch_idx < len(eyecatch_insert_points) and i == eyecatch_insert_points[eyecatch_idx]:
            cur += eyecatch_durations[eyecatch_idx]
            eyecatch_idx += 1
        label = format_comment(clip_metadata[i])
        # クリップの開始時刻をタイムスタンプとして記録
        timestamps.append((cur, label))
        start_sec = clip_metadata[i].get('start_sec')
        end_sec = clip_metadata[i].get('end_sec')
        if start_sec is not None and end_sec is not None:
            try:
                cur += float(end_sec) - float(start_sec)
            except Exception:
                cur += 10.0
        else:
            cur += 10.0
    # EDの開始時刻をタイムスタンプとして記録
    timestamps.append((cur, 'Ending' if group_id == "hololive_en" else 'エンディング'))
    # テキスト生成
    lines = []
    lines.append(video_title)
    lines.append('')
    lines.append('Stream URL' if group_id == "hololive_en" else '配信URL')
    lines.append(video_url)
    lines.append('')
    # Xの紹介文とURLを追加
    x_text = "We also post data and graphs on X!" if group_id == "hololive_en" else "X（旧Twitter）でもデータやグラフをポスト中！"
    lines.append(x_text)
    lines.append(twitter_url)
    lines.append('')
    lines.append('Timestamps' if group_id == "hololive_en" else 'タイムスタンプ一覧')
    for t, label in timestamps:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        # クリップの一言（コメント）が空でなければ表示
        if label:
            lines.append(f"{h:01}:{m:02}:{s:02} {label}")
        else:
            lines.append(f"{h:01}:{m:02}:{s:02}")
    txt_path = os.path.join(os.path.dirname(output_video), '概要欄.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"[INFO] 概要欄.txt を出力: {txt_path}")
    return output_video
# 例外処理は関数全体ではなく個別で行う

def create_op_from_clips(clip_video_paths, output_path, total_op_duration=9, combine_order=None):
    """
    OP動画を作成する関数。
    各クリップ元動画から音声が最も大きい部分を中心に、OP全体で9秒になるように分割して抜き出し、結合する。
    clip_video_paths: 元動画のパスリスト
    output_path: OP動画の出力先
    total_op_duration: OP全体の秒数（デフォルト9秒）
    """
    segment_duration = total_op_duration / len(clip_video_paths)
    temp_segments = []
    for video_path in clip_video_paths:
        # 一時wavファイルに音声抽出
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:
            wav_path = tmp_wav.name
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            "-loglevel", "error", 
            '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', wav_path
        ]
        subprocess.run(cmd, check=True)
        # 音声データ読み込み
        data, samplerate = sf.read(wav_path)
        if len(data) == 0:
            print(f"[ERROR] 音声抽出失敗: {video_path}")
        abs_data = np.abs(data)
        seg_samples = int(segment_duration * samplerate)
        # 最大音量部分の中心を探す
        if len(abs_data) <= seg_samples:
            start_idx = 0
        else:
            window_sums = np.convolve(abs_data, np.ones(seg_samples), 'valid')
            max_idx = np.argmax(window_sums)
            start_idx = max(0, max_idx + seg_samples//2 - seg_samples//2)
        start_sec = start_idx / samplerate
        end_sec = start_sec + segment_duration
        # 動画長取得と範囲調整
        try:
            video_duration = 35
        except Exception as e:
            print(f"[ERROR] 動画長取得失敗: {video_path}, {e}")
            video_duration = None
        if video_duration is not None and start_sec + segment_duration > video_duration:
            start_sec = max(0, video_duration - segment_duration)
            print(f"[WARN] 切り出し範囲調整: start_sec={start_sec}, segment_duration={segment_duration}, video_duration={video_duration}")
        print(f"[DEBUG] start_sec={start_sec}, segment_duration={segment_duration}, video_path={video_path}")
        # 一時動画ファイルに抜き出し（フェード＋リサイズ付き）
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_vid:
            seg_path = tmp_vid.name
        # 切り抜き＋リサイズのみ（フェードなし）
        filter_resize = "scale=1920:1080"
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            "-loglevel", "error", 
            '-ss', str(start_sec), '-t', str(segment_duration),
            '-vf', filter_resize,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', seg_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(f"[ERROR] ffmpeg failed: {result.stderr.decode()}")
        temp_segments.append(seg_path)
        os.remove(wav_path)
        # --- 全抜き出し動画を結合（concat_temp_path生成） ---
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_list:
        list_path = tmp_list.name
        with open(list_path, 'w', encoding='utf-8') as f:
            for seg in temp_segments:
                f.write(f"file '{seg}'\n")
    concat_temp_path = output_path + ".tmp.mp4"
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,"-loglevel", "error", 
        '-c', 'copy', concat_temp_path
    ]
    subprocess.run(cmd, check=True)
    # --- スコアオーバーレイ画像シーケンス生成 ---
    # combine_orderは引数で渡す前提
    # 動画ID取得
    # video_idはcombine_orderから取得
    video_id = None
    if combine_order and isinstance(combine_order, list) and len(combine_order) > 0:
        video_id = combine_order[0].get('video_id')
    if not video_id:
        raise ValueError('video_idがcombine_orderから取得できませんでした')
    # scores.jsonロード
    scores_path = os.path.join('backend', 'data', 'scores', f'{video_id}_scores.json')
    with open(scores_path, encoding='utf-8') as f:
        scores_data = json.load(f)
    # combine_orderから各クリップの開始時刻取得
    # クリップ数
    N = len(combine_order)
    # 1クリップあたりの必要データ数
    total_frames = int(total_op_duration * 30)
    step = 4
    overlay_count = total_frames // step
    per_clip_count = int(overlay_count / N)
    # 各クリップからデータ抽出
    # シンプルなロジック: 270枚分のデータを順番に用意し、10秒ごとに集計した値をstep=4枚ずつ繰り返す
    total_frames = int(total_op_duration * 30)
    interval_sec = 10
    overlay_scores = []
    # combine_orderの各クリップについて、start_secから10秒ごとに集計
    for clip in combine_order:
        start_sec = int(clip.get('start_sec', 0))
        for i in range(0, total_frames, step):
            begin = start_sec + (i // step) * interval_sec
            end = begin + interval_sec
            section = [s for s in scores_data if begin <= s['timestamp'] < end]
            agg = {
                'timestamp': begin,
                'comment_count': sum(s.get('comment_count', 0) for s in section),
                'laugh_score': sum(s.get('laugh_score', 0) for s in section),
                'healing_score': sum(s.get('healing_score', 0) for s in section),
                'chaos_score': sum(s.get('chaos_score', 0) for s in section)
            }
            overlay_scores.extend([agg] * step)
    # 必要枚数だけに切り詰め
    overlay_scores = overlay_scores[:total_frames]
    # --- 画像シーケンス生成 ---
    temp_overlay_dir = tempfile.mkdtemp()
    font_path = os.path.join('backend/data', 'LightNovelPOPv2.otf')
    font_size = 60
    outline_width = 4
    colors = [(106,255,68), (255,255,25), (0,212,255), (255,143,255)] # 緑,黄,青,ピンク
    labels = ['コメント数', '爆笑指数', 'かわいさ指数', '盛り上がり指数']
    score_keys = ['comment_count', 'laugh_score', 'healing_score', 'chaos_score']
    for i, score in enumerate(overlay_scores):
        img = Image.new('RGBA', (1920, 1080), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception as e:
            print(f"[DEBUG] font load error: {e}")
            font = ImageFont.load_default()
        for j, (label, key, color) in enumerate(zip(labels, score_keys, colors)):
            value = score.get(key, 0)
            x, y = 10, 10 + j * (font_size + 20)
            text = f"{label}: {value}"
            # 縁取り
            draw.text((x, y), text, font=font, fill=(128,128,128), stroke_width=outline_width, stroke_fill=(128,128,128))
            # 本体
            draw.text((x, y), text, font=font, fill=(255,255,255), stroke_width=0)
            # ラベル色（左端のラベル部分だけ色を付ける）
            draw.text((x, y), label, font=font, fill=color, stroke_width=0)
        img_path = os.path.join(temp_overlay_dir, f"{i:06d}.png")
        img.save(img_path)
        # print(f"[DEBUG] saved overlay image: {img_path}")
    # --- OP動画にオーバーレイ合成 ---
    overlay_pattern = os.path.join(temp_overlay_dir, "%06d.png")
    overlayed_op_path = output_path + ".overlay.mp4"
    filter_complex = f"""
    [1:v]format=rgba[ov];
    [0:v][ov]overlay=0:0:shortest=1[v]
    """.strip().replace("\n", "")

    cmd = [
        'ffmpeg', '-y',
        '-i', concat_temp_path,
        "-loglevel", "error", 
        '-framerate', '30', '-i', overlay_pattern,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '0:a?',  # 音声があればコピー
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-movflags', '+faststart',
        overlayed_op_path
    ]

    print(f"[DEBUG] ffmpeg overlay command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[DEBUG] ffmpeg overlay stdout: {result.stdout}")
    print(f"[DEBUG] ffmpeg overlay stderr: {result.stderr}")
    if result.returncode != 0:
        print(f"[ERROR] ffmpeg overlay failed with code {result.returncode}")
    # 以降の処理でconcat_temp_pathの代わりにoverlayed_op_pathを使う
    concat_temp_path = overlayed_op_path
    # analyzing.mp4（グリーンバック）をOPにクロマキー合成（存在すれば）
    overlay_mp4_path = os.path.abspath('backend/static/images/OP_overlay/analyzing.mp4')
    analyzing_out_path = output_path + "_analyzing.mp4"
    if os.path.exists(overlay_mp4_path):
        filter_overlay = (
            '[0:v]scale=1920:1080[bg];'
            '[1:v]scale=1920:1080,chromakey=0x00FF00:0.2:0.1[ov];'
            '[bg][ov]overlay=0:0:format=auto:enable=\'between(t,0,20)\''
        )
        cmd = [
            'ffmpeg', '-y', '-i', concat_temp_path, '-i', overlay_mp4_path,
            "-loglevel", "error", 
            '-filter_complex', filter_overlay,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-movflags', '+faststart',
            analyzing_out_path
        ]
        subprocess.run(cmd, check=True)
        concat_temp_path = analyzing_out_path
    # 必ず背景ブラーを追加
    blur_out_path = output_path + "_blur.mp4"
    filter_blur_resize = (
        '[0:v]scale=2112:1188,boxblur=5:1[bg];'
        '[0:v]scale=1920:1080[fg];'
        '[bg][fg]overlay=(W-w)/2:(H-h)/2,scale=1920:1080'
    )
    cmd = [
        'ffmpeg', '-y', '-i', concat_temp_path,
        "-loglevel", "error", 
        '-filter_complex', filter_blur_resize,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-movflags', '+faststart',
        blur_out_path
    ]
    subprocess.run(cmd, check=True)
    concat_temp_path = blur_out_path
    # analysis_complete.mp4合成（concatで結合）
    overlay_path = os.path.abspath('backend/static/images/OP_overlay/analysis_complete.mp4')
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_list:
        list_path = tmp_list.name
        with open(list_path, 'w', encoding='utf-8') as f:
            f.write(f"file '{concat_temp_path}'\n")
            if os.path.exists(overlay_path):
                f.write(f"file '{overlay_path}'\n")
    final_out_path = output_path
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,
        "-loglevel", "error", 
        '-c', 'copy', final_out_path
    ]
    subprocess.run(cmd, check=True)
    # 一時ファイル削除
    for seg in temp_segments:
        os.remove(seg)
    os.remove(list_path)
    if os.path.exists(concat_temp_path):
        os.remove(concat_temp_path)
    return output_path