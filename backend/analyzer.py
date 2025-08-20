"""
YouTube Clipper Backend Main Module
"""


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
from visualization import plot_excitement_graph, create_comment_heatmap, plot_comment_count_graph, concat_graphs_horizontal, create_vertical_score_graphs, plot_score_graph, plot_multi_score_graph, combine_graphs_to_canvas,plot_twitter_graphs

# slide_graphs_to_video
from slide_graphs_to_video import add_sliding_graphs_to_video

# ASS utilities
from ass_utils import (
    create_ass_file, combine_video_and_ass, add_ass_subtitles_to_ed, create_ass_from_whisper, create_ass_file_9x16, run_whisper_on_video, whisper_segments_to_ass_data
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
from create_clip_sheet import create_clip_sheet_from_process_video, set_combine_flag_true, create_subs_sheet_from_process_video
# Clip_util
from clip_util import generate_clips_with_ass,create_op_from_clips,concat_clips_with_eyecatch

########################統合・メイン処理始まり

def process_video(video_url, duration_minutes, skip_intro=False, intro_duration_minutes=3, skip_ending=False, ending_duration_minutes=3, is_premiere=None, countdown_minutes=None, use_cache=True, group_id=None):
    # --- 配信者情報の一元管理: summary_streamers.jsonを参照し、なければcreator_engのみ手動入力 ---
    summary_streamers_path = os.path.join(os.path.dirname(__file__), 'data', 'summary_streamers.json')
    # 動画のメタデータを取得
    metadata = get_video_metadata(video_url)
    channel_name = metadata.get('channel', '')
    creator_eng = ''
    # summary_streamers.jsonを読み込み
    if os.path.exists(summary_streamers_path):
        with open(summary_streamers_path, 'r', encoding='utf-8') as f:
            streamer_db = json.load(f)
    else:
        streamer_db = {}
    # 既存配信者か判定
    if channel_name in streamer_db:
        creator_eng = streamer_db[channel_name].get('creator_eng', '')
    else:
        print(f"新規配信者です: {channel_name}")
        creator_eng = input(f"英語名(creator_eng)を入力してください [{channel_name}]: ")
    # group_id/group_nameは従来通り
    # group_idが未指定の場合はデフォルト"hololive"に
    if group_id is None:
        print("グループIDが未指定のため、デフォルトのホロライブを使用します")
        group_id = "hololive"

    # duration_minutes から動画の総秒数を計算
    total_seconds = duration_minutes * 60

    if group_id == "hololive":
        group_name = "ホロライブ"
    elif group_id == "nijisanji":
        group_name = "にじさんじ"
    elif group_id == "hololive_en":
        group_name = "ホロライブEN"
    else:
        print(f"❌ 無効なグループ指定です: {group_id}")
        raise ValueError(f"Invalid group_id: {group_id}")


    # 動画のメタデータを取得
    metadata = get_video_metadata(video_url)
    video_title = metadata.get('title', '')
    channel_name = metadata.get('channel', '')
    # --- analyzer.pyから移動した関数は外部モジュールからimport ---
    # すべてファイル冒頭でimport済み
    # group_idが未指定の場合はデフォルト"hololive"に

    print(f"コメントを取得中: {video_url}")

    # 動画時間の自動取得（duration_minutesが0または未指定の場合）
    if duration_minutes <= 0:
        video_duration_seconds = metadata.get('duration', 0)
        if video_duration_seconds > 0:
            duration_minutes = video_duration_seconds / 60
            print(f"動画時間を自動取得: {duration_minutes:.2f}分 ({video_duration_seconds}秒)")
        else:
            print("警告: 動画時間を取得できませんでした。デフォルト値（30分）を使用します。")
            duration_minutes = 30
    else:
        print(f"動画時間（手動指定）: {duration_minutes}分")
    
    # カウントダウン時間を分から秒に変換
    premiere_offset = None
    if is_premiere and countdown_minutes is not None:
        premiere_offset = countdown_minutes * 60  # 分を秒に変換
        print(f"プレミア公開設定: カウントダウン {countdown_minutes}分 ({premiere_offset}秒)")
    
    # コメント取得（キャッシュ対応）
    if use_cache:
        print("キャッシュからコメント読み込みを試行中...")
        comments = load_comments_from_cache(video_url)
        if comments is None:
            print("キャッシュが見つからないため、新規取得します...")
            comments = get_comments(video_url, intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, video_duration_minutes=duration_minutes, is_premiere=is_premiere, premiere_offset=premiere_offset)
            save_comments_to_cache(video_url, comments)
            generate_chart_data_from_comments(video_url, comments)
            print(f"新規取得・キャッシュ保存完了: {len(comments)}件のコメント")
        else:
            print(f"キャッシュから読み込み完了: {len(comments)}件のコメント")
    else:
        # 従来通りの処理（キャッシュを使わない）
        comments = get_comments(video_url, intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, video_duration_minutes=duration_minutes, is_premiere=is_premiere, premiere_offset=premiere_offset)
        print(f"{len(comments)}件のコメントを取得しました")

    if not comments:
        print("WARNING: No comments retrieved!")
        comments = []  # 空のリストを保証

    # クリップ抽出失敗時もclips: []を返すためのエラーハンドリング用
    video_id = extract_video_id(video_url)
    channel_dir = os.path.join('backend', 'clips', sanitize_filename(channel_name))
    video_specific_dir = os.path.join(channel_dir, video_id)
    video_path = os.path.join(video_specific_dir, f"{video_id}.mp4")

    # チャンネルフォルダを先に作成
    if not os.path.exists(channel_dir):
        os.makedirs(channel_dir, exist_ok=True)

    # 動画フォルダを作成
    if not os.path.exists(video_specific_dir):
        os.makedirs(video_specific_dir, exist_ok=True)

    
    # 導入部分のコメント数を表示
    intro_comments = [c for c in comments if c.get('is_intro', False)]
    ending_comments = [c for c in comments if c.get('is_ending', False)]
    print(f"導入部分のコメント数: {len(intro_comments)}件")
    print(f"エンディング部分のコメント数: {len(ending_comments)}件")
    print(f"クリップ生成時に導入部分をスキップ: {skip_intro}")
    print(f"クリップ生成時にエンディング部分をスキップ: {skip_ending}")
    
    # プレミア公開の場合の追加情報
    if is_premiere:
        actual_start_comments = [c for c in comments if c['timestamp'] >= 0]
        print(f"実際の配信開始後のコメント数: {len(actual_start_comments)}件")
    
    print("コメント内容を分析中...")
    print(f"  コメント総数: {len(comments)}")
    if len(comments) > 0:
        comments_with_scores = analyze_comment_content(comments)
        print(f"  analyze_comment_content後: {len(comments_with_scores)}件")
    
    # グラフ用：全データで分析（導入部分を含む）
    print("グラフ用の全体分析中...")
    try:
        # グラフ用は全区間（イントロ・エンディング含む）でスコア計算
        excitement_df_full = analyze_excitement(comments_with_scores, duration_minutes, window_size_seconds=1, intro_duration_minutes=0, ending_duration_minutes=0)
        # スムージング適用
        excitement_df_full = smooth_scores(excitement_df_full, window_sec=7)
        print(f"✓ excitement_df_full created: shape={excitement_df_full.shape}")
        print(f"  Columns: {list(excitement_df_full.columns)}")
        # 1秒ごとのスコア・コメント数を保存
        save_per_second_scores(excitement_df_full, video_id)
    except Exception as e:
        print(f"✗ ERROR in analyze_excitement: {e}")
        import traceback
        traceback.print_exc()
        # 空のDataFrameを作成
        excitement_df_full = pd.DataFrame({
            'start_time': [],
            'end_time': [],
            'comment_count': [],
            'positive_score': [],
            'excitement_score': [],
            'comments': []
        })
        # 重大なエラー時はclips: []で返す
        return error_result("Error in analyze_excitement", {'exception': str(e)})
    
    # クリップ用：導入部分をスキップして分析
    print("クリップ用の分析中（導入部分を除外）...")
    try:
        excitement_df_clip = analyze_excitement(comments_with_scores, duration_minutes, intro_duration_minutes=intro_duration_minutes,ending_duration_minutes=ending_duration_minutes )
    except Exception as e:
        print(f"✗ ERROR in analyze_excitement (clip): {e}")
        import traceback
        traceback.print_exc()
        return error_result("Error in analyze_excitement (clip)", {'exception': str(e)})
    print(f"  excitement_df_clip shape: {getattr(excitement_df_clip, 'shape', None)}")
    print(f"  excitement_df_clip columns: {list(excitement_df_clip.columns) if hasattr(excitement_df_clip, 'columns') else 'No columns'}")
    print("盛り上がりポイントを検出中...")

    # === 新マルチ感情クリップ抽出ロジック ===
    print("マルチ感情クリップ抽出中...")
    # クリップ抽出範囲を決定
    if skip_intro:
        intro_duration_seconds = intro_duration_minutes * 60
        min_start_seconds = intro_duration_seconds
    else:
        min_start_seconds = 0
    total_seconds = duration_minutes * 60
    if skip_ending:
        max_end_seconds = max(total_seconds - ending_duration_minutes * 60, min_start_seconds)
    else:
        max_end_seconds = total_seconds  # Noneではなく明示的に動画長を渡す

    # 対象コメントを範囲でフィルタ
    filtered_comments = [c for c in comments_with_scores if c.get('timestamp', 0) >= min_start_seconds and (max_end_seconds is None or c.get('timestamp', 0) <= max_end_seconds)]
    print(f"  filtered_comments: {len(filtered_comments)}件 (min_start_seconds={min_start_seconds}, max_end_seconds={max_end_seconds})")


    # --- スムージング済み1秒ごとデータから10秒枠で1秒ずつスライドし合計値が高い区間を抽出 ---
    # min/max範囲
    min_start = min_start_seconds
    max_end = max_end_seconds if max_end_seconds is not None else total_seconds
    multi_emotion_result = {}
    label_jp_map = {'laugh': '爆笑指数', 'healing': 'かわいさ指数', 'chaos': '盛り上がり指数'}
    for label in ['laugh', 'healing', 'chaos']:
        col = f'smoothed_{label}_score'
        if col in excitement_df_full.columns:
            arr = excitement_df_full[col].values
            starts = [int(x) for x in excitement_df_full['start_time'].values]
            ends = [int(x) for x in excitement_df_full['end_time'].values]
            n = len(arr)
            exclude_min = 0
            exclude_max = 0
            for i in range(n - 10 + 1):
                s = int(starts[i])
                e = int(ends[i + 10 - 1])
                if (min_start is not None and s < min_start):
                    exclude_min += 1
                elif (max_end is not None and e > max_end):
                    exclude_max += 1
            multi_emotion_result[label] = extract_top_windows(
                excitement_df_full, col, window_size=10, top_n=100, min_start=min_start, max_end=max_end
            )
            if len(multi_emotion_result[label]) > 0:
                pass
        else:
            multi_emotion_result[label] = []
    for label, periods in multi_emotion_result.items():
        label_jp = label_jp_map.get(label, label)
        print(f"  {label_jp}: {len(periods)} periods")



    # --- ラベルごとに候補抽出・多段マージ・top3選出のみ ---
    try:
        final_clips = ensure_top3_per_emotion(
            multi_emotion_result,
            min_start_seconds,
            max_end_seconds,
            total_seconds,
            multi_stage_timewise_merge,
            extract_best_subclip,
            excitement_df_full
        )
    except Exception as e:
        print(f"✗ ERROR in ensure_top3_per_emotion: {e}")
        import traceback
        traceback.print_exc()
        return error_result("Error in ensure_top3_per_emotion", {'exception': str(e)})
    if not isinstance(final_clips, list):
        final_clips = []

    # メタデータ付与（コメント数・サンプルコメント・クリップURL等）
    try:
        clips = add_metadata_to_clips(final_clips, video_url, comments_with_scores, excitement_df_full=excitement_df_full)
    except Exception as e:
        print(f"✗ ERROR in add_metadata_to_clips: {e}")
        import traceback
        traceback.print_exc()
        return error_result("Error in add_metadata_to_clips", {'exception': str(e)})
    if not isinstance(clips, list):
        clips = []
    print(f"抽出クリップ数: {len(clips)} (各感情3本ずつ)")


    # クリップ情報をresultに格納
    result_clips = []
    # --- クリップごとにコメント選択・clip情報付与・JSON保存 ---
    draw_comments_all = []
    draw_comments_dir = os.path.join('backend', 'data', 'draw_comments')
    if not os.path.exists(draw_comments_dir):
        os.makedirs(draw_comments_dir, exist_ok=True)
    for idx, c in enumerate(clips):
        main_label = c.get('main_label')
        window_score = c.get('window_score', None)
        max_scores = c.get('max_scores', {})
        # int/float変換でint64を防ぐ
        def to_py_num(val):
            if hasattr(val, 'item'):
                return val.item()
            if isinstance(val, (np.integer, np.floating)):
                return val.tolist()
            return float(val) if isinstance(val, (int, float, np.number, np.generic)) else val

        rounded_scores = {k: int(round(float(v))) for k, v in c.get('scores', {}).items()}
        try:
            result_clips.append({
                'url': str(c['url']),
                'start_time': float(c['start_time']) if isinstance(c.get('start_time'), (int, float)) else c.get('start_time'),
                'end_time': float(c['end_time']) if isinstance(c.get('end_time'), (int, float)) else c.get('end_time'),
                'start': float(c['start']) if isinstance(c.get('start'), (int, float)) else c.get('start'),
                'end': float(c['end']) if isinstance(c.get('end'), (int, float)) else c.get('end'),
                'duration': float(c['duration']) if isinstance(c.get('duration'), (int, float)) else c.get('duration'),
                'labels': c['labels'],
                'main_label': main_label,
                'scores': {k: to_py_num(v) for k, v in c.get('scores', {}).items()},
                'window_score': to_py_num(window_score),
                'max_scores': {k: to_py_num(v) for k, v in max_scores.items()},
                'rank': c['rank'],
                'comment_count': int(c['comment_count']) if c.get('comment_count') is not None else 0,
                'videoId': video_id,
                'channelName': channel_name,
                'group_id': group_id
            })
        except Exception as e:
            print(f"[ERROR] クリップ情報result_clips格納時: {e}")
        # --- クリップごとにコメント選択 ---
        def safe_to_float(val):
            if isinstance(val, str) and ':' in val:
                try:
                    return time_to_seconds(val)
                except Exception:
                    print(f"[ERROR] time_to_seconds変換失敗: {val}")
                    return 0.0
            try:
                return float(val)
            except Exception:
                print(f"[ERROR] float変換失敗: {val}")
                return 0.0
        clip_start = safe_to_float(c.get('start_time', 0))
        clip_end = safe_to_float(c.get('end_time', 0))
        # print(f"[DEBUG] clip_start: {clip_start}, clip_end: {clip_end}")
        clip_id = f"clip_{idx+1:03d}"
        clip_rank = c.get('rank')
        # クリップ範囲内のコメント抽出
        try:
            clip_comments = [com for com in comments_with_scores if clip_start <= float(com.get('timestamp', 0)) <= clip_end]
        except Exception as e:
            print(f"[ERROR] クリップ範囲コメント抽出時: {e}")
            clip_comments = []
        # print(f"[DEBUG] clip_comments({len(clip_comments)})件")
        # コメント選択アルゴリズム適用
        try:
            selected_comments = select_comments_per_second(clip_comments)
        except Exception as e:
            print(f"[ERROR] コメント選択アルゴリズム適用時: {e}")
            selected_comments = []
        # 各コメントにclip情報付与
        for com in selected_comments:
            com['clip_id'] = clip_id
            com['clip_rank'] = clip_rank
            com['clip_start'] = clip_start
            com['clip_end'] = clip_end
            com['main_label'] = main_label
            # int64/float64をPython型に
            for k, v in list(com.items()):
                if hasattr(v, 'item'):
                    com[k] = v.item()
                elif isinstance(v, (np.integer, np.floating)):
                    com[k] = v.tolist()
                elif isinstance(v, (int, float, np.number, np.generic)):
                    com[k] = float(v)
        draw_comments_all.extend(selected_comments)
    
    # まとめてJSON保存
    video_id = extract_video_id(video_url)
    draw_comments_path = os.path.join(draw_comments_dir, f"{video_id}.json")
    try:
        with open(draw_comments_path, 'w', encoding='utf-8') as f:
            json.dump(draw_comments_all, f, ensure_ascii=False, indent=2)
        print(f"✓ クリップごと選択コメントを保存: {draw_comments_path} ({len(draw_comments_all)}件)")
    except Exception as e:
        print(f"✗ draw_comments保存エラー: {e}")

    # Gemini用プロンプト・データを保存
    gemini_prompt_path, gemini_prompt_txt_path = save_gemini_prompt_and_data(
    draw_comments_all, channel_name, video_id
    )


    # Gemini CLIの出力先
    gemini_output_path = os.path.join("backend", "clips", sanitize_filename(channel_name), video_id, "gemini_output.json")

    # Gemini CLIコマンド例（適宜パスやオプションを調整）
    # Gemini CLI: stdin/stdout方式に修正
    try:
        with open(gemini_prompt_txt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
            result = subprocess.run(
                'gemini -m gemini-2.5-flash -p',
                input=prompt,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
        with open(gemini_output_path, "w", encoding="utf-8") as f:
            f.write(result.stdout or "")
        print("[INFO] Gemini CLI呼び出し成功")
        print("stdout:\n", result.stdout)
        print("stderr:\n", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Gemini CLI呼び出し失敗: {e}")
        print("stdout:\n", e.stdout)
        print("stderr:\n", e.stderr)
    except Exception as e:
        print(f"[ERROR] Gemini CLI実行に失敗: {e}")

    # Gemini出力jsonをパースして一言jsonを保存
    gemini_comments_json_path = parse_and_save_gemini_output(
        gemini_output_path, video_id
    )  

    print("クリップURL生成中...")
    # clipsは必ずリスト型で返す（空でも[]）
    clip_urls = result_clips if isinstance(result_clips, list) else []
    if not isinstance(clip_urls, list):
        clip_urls = []
    if clip_urls is None:
        clip_urls = []

    print("カスタム絵文字辞書作成中...")
    process_emojis_if_needed(video_id, channel_name)

    
    # グラフを生成（全データを使用、スムージング済みデータで出力）
    print("グラフを生成中 (スムージング済みデータ使用)...")
    graph_paths = {}
    relative_path = os.path.join(sanitize_filename(channel_name), video_id)

    try :
        # intro/endingがFalseなら0を使う
        intro_val = intro_duration_minutes if skip_intro else 0
        ending_val = ending_duration_minutes if skip_ending else 0



        # 2. 爆笑指数グラフ（smoothed_laugh_score）
        laugh_graph_filename = f"laugh_graph_{intro_val}_{ending_val}.png"
        laugh_graph_rabeled_filename = f"laugh_graph_{intro_val}_{ending_val}_rabeled.png"
        laugh_graph_path = os.path.join(video_specific_dir, laugh_graph_filename)
        laugh_graph_rabeled_path = os.path.join(video_specific_dir, laugh_graph_rabeled_filename)
        col = 'smoothed_laugh_score' if 'smoothed_laugh_score' in excitement_df_full.columns else 'laugh_score'
        plot_score_graph(graph_width=1280, graph_height=360, excitement_df=excitement_df_full, score_col=col, output_path=laugh_graph_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=False)
        # ラベル付きグラフも生成
        plot_score_graph(graph_width=1280, graph_height=720, excitement_df=excitement_df_full, score_col=col, output_path=laugh_graph_rabeled_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=True)
        graph_paths['laugh_graph'] = os.path.join(relative_path, laugh_graph_filename).replace('\\', '/')
        graph_paths['laugh_graph_rabeled'] = os.path.join(relative_path, laugh_graph_rabeled_filename).replace('\\', '/')
        print(f"爆笑指数グラフを生成: {laugh_graph_path}")

        # 3. かわいさ指数グラフ（smoothed_healing_score）
        healing_graph_filename = f"healing_graph_{intro_val}_{ending_val}.png"
        healing_graph_rabeled_filename = f"healing_graph_{intro_val}_{ending_val}_rabeled.png"
        healing_graph_path = os.path.join(video_specific_dir, healing_graph_filename)
        healing_graph_rabeled_path = os.path.join(video_specific_dir, healing_graph_rabeled_filename)
        col = 'smoothed_healing_score' if 'smoothed_healing_score' in excitement_df_full.columns else 'healing_score'
        plot_score_graph(graph_width=1280, graph_height=360, excitement_df=excitement_df_full, score_col=col, output_path=healing_graph_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=False)
        # ラベル付きグラフも生成
        plot_score_graph(graph_width=1280, graph_height=720, excitement_df=excitement_df_full, score_col=col, output_path=healing_graph_rabeled_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=True)
        graph_paths['healing_graph'] = os.path.join(relative_path, healing_graph_filename).replace('\\', '/')
        graph_paths['healing_graph_rabeled'] = os.path.join(relative_path, healing_graph_rabeled_filename).replace('\\', '/')
        print(f"かわいさ指数グラフを生成: {healing_graph_path}")

        # 4. 盛り上がり指数グラフ（smoothed_chaos_score）
        chaos_graph_filename = f"chaos_graph_{intro_val}_{ending_val}.png"
        chaos_graph_rabeled_filename = f"chaos_graph_{intro_val}_{ending_val}_rabeled.png"
        chaos_graph_path = os.path.join(video_specific_dir, chaos_graph_filename)
        chaos_graph_rabeled_path = os.path.join(video_specific_dir, chaos_graph_rabeled_filename)
        col = 'smoothed_chaos_score' if 'smoothed_chaos_score' in excitement_df_full.columns else 'chaos_score'
        plot_score_graph(graph_width=1280, graph_height=360, excitement_df=excitement_df_full, score_col=col, output_path=chaos_graph_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=False)
        # ラベル付きグラフも生成
        plot_score_graph(graph_width=1280, graph_height=720, excitement_df=excitement_df_full, score_col=col, output_path=chaos_graph_rabeled_path,
                        intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes, with_label=True)
        graph_paths['chaos_graph'] = os.path.join(relative_path, chaos_graph_filename).replace('\\', '/')
        graph_paths['chaos_graph_rabeled'] = os.path.join(relative_path, chaos_graph_rabeled_filename).replace('\\', '/')
        print(f"盛り上がり指数グラフを生成: {chaos_graph_path}")

        # 5. 3スコア合成グラフ（smoothed_列を使いたい場合は列名を差し替えて渡す）
        multi_graph_filename = f"multi_score_graph_{intro_val}_{ending_val}.png"
        multi_graph_path = os.path.join(video_specific_dir, multi_graph_filename)
        # smoothed列があれば一時的に差し替えて渡す
        df_for_multi = excitement_df_full.copy()
        if 'smoothed_laugh_score' in df_for_multi.columns:
            df_for_multi['laugh_score'] = df_for_multi['smoothed_laugh_score']
        if 'smoothed_healing_score' in df_for_multi.columns:
            df_for_multi['healing_score'] = df_for_multi['smoothed_healing_score']
        if 'smoothed_chaos_score' in df_for_multi.columns:
            df_for_multi['chaos_score'] = df_for_multi['smoothed_chaos_score']
        plot_multi_score_graph(df_for_multi, multi_graph_path,
                              intro_duration_minutes=intro_duration_minutes, ending_duration_minutes=ending_duration_minutes, duration_minutes=duration_minutes)
        # 3つのスコアグラフを合成
        sanitized_channel = sanitize_filename(channel_name)
        clip_dir = os.path.join('g:/マイドライブ/clips', sanitized_channel, video_id)
        if not os.path.exists(clip_dir):
            os.makedirs(clip_dir, exist_ok=True)
        # combined_graph_path = os.path.join(clip_dir, "combined_score_graph.png")
        # combine_graphs_to_canvas([
        #     laugh_graph_path,
        #     healing_graph_path,
        #     chaos_graph_path
        # ], combined_graph_path)
        # graph_paths['combined_score_graph'] = os.path.join(relative_path, "combined_score_graph.png").replace('\\', '/')
        # print(f"3つのスコアグラフを合成: {combined_graph_path}")
        graph_paths['multi_score_graph'] = os.path.join(relative_path, multi_graph_filename).replace('\\', '/')
        print(f"3スコア合成グラフを生成: {multi_graph_path}")

        # 6. コメント数グラフ（全データ使用）
        comment_count_graph_filename = f"comment_count_graph_{intro_val}_{ending_val}.png"
        comment_count_graph_rabeled_filename = f"comment_count_graph_rabeled_{intro_val}_{ending_val}.png"
        comment_count_graph_path = os.path.join(video_specific_dir, comment_count_graph_filename)
        comment_count_graph_rabeled_path = os.path.join(video_specific_dir, comment_count_graph_rabeled_filename)
        plot_comment_count_graph(graph_width=1280, graph_height=360, excitement_df=excitement_df_full, output_path=comment_count_graph_path, duration_minutes=duration_minutes, with_label=False)
        # ラベル付きグラフも生成
        plot_comment_count_graph(graph_width=1280, graph_height=720, excitement_df=excitement_df_full, output_path=comment_count_graph_rabeled_path, duration_minutes=duration_minutes, with_label=True)
        graph_paths['comment_count_graph_rabeled'] = os.path.join(relative_path, comment_count_graph_rabeled_filename).replace('\\', '/')
        graph_paths['comment_count_graph'] = os.path.join(relative_path, comment_count_graph_filename).replace('\\', '/')

        # 横長の合成画像を作成
        combined_all_graph_path = os.path.join(video_specific_dir, "combined_all_graph.png")
        rabeled_graph_paths = [
            os.path.join('backend', 'clips', graph_paths['comment_count_graph_rabeled']),
            os.path.join('backend', 'clips', graph_paths['laugh_graph_rabeled']),
            os.path.join('backend', 'clips', graph_paths['healing_graph_rabeled']),
            os.path.join('backend', 'clips', graph_paths['chaos_graph_rabeled'])
        ]
        concat_graphs_horizontal(graph_paths=rabeled_graph_paths, output_path=combined_all_graph_path)
        create_vertical_score_graphs(
            comment_graph_path=comment_count_graph_path,
            laugh_graph_path=laugh_graph_path,
            healing_graph_path=healing_graph_path,
            chaos_graph_path=chaos_graph_path,
            output_dir=clip_dir
        )

        # twitter用のグラフを生成
        plot_twitter_graphs(
            excitement_df=excitement_df_full,
            output_dir=video_specific_dir,
            duration_minutes=duration_minutes,
            num_bins=240
        )

        # ヒートマップも生成（全データ使用）
        heatmap_filename = 'comment_heatmap.png'
        heatmap_path = os.path.join(video_specific_dir, heatmap_filename)
        create_comment_heatmap(comments_with_scores, duration_minutes, 
                             output_path=heatmap_path)
        graph_paths['comment_heatmap'] = os.path.join(relative_path, heatmap_filename).replace('\\', '/')
        print(f"コメントヒートマップを生成: {heatmap_path}")
    except Exception as e:
        print(f"グラフ生成エラー: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # フロントエンド用のチャートデータ（全データを使用、スムージング済みスコアも含める）
    try:
        print(f"Creating chart data from {len(excitement_df_full)} rows (smoothed scores included)...")
        generate_chart_data_from_comments(video_url, comments_with_scores)
    except Exception as e:
        print(f"✗ チャートデータ作成エラー: {e}")
        print(f"  excitement_df_full type: {type(excitement_df_full)}")
        print(f"  excitement_df_full columns: {list(excitement_df_full.columns) if hasattr(excitement_df_full, 'columns') else 'No columns'}")
        import traceback
        traceback.print_exc()
    chart_data = []  # excitementScoreは含めず空リスト
    
    # 統計情報
    total_comments = len(comments)
    intro_comments_count = len([c for c in comments if c.get('is_intro', False)])
    ending_comments_count = len([c for c in comments if c.get('is_ending', False)])
    analyzed_comments = total_comments - (intro_comments_count if skip_intro else 0) - (ending_comments_count if skip_ending else 0)
    custom_emoji_stats = analyze_custom_emojis(comments)

    # 平均コメント数/分と最大コメント数/10秒を計算
    duration_seconds = duration_minutes * 60
    avg_comments_per_minute = total_comments / duration_minutes if duration_minutes > 0 else 0
    max_comments_10sec = calculate_max_comments_per_interval(comments, duration_seconds, 10)

    # プレミア公開の追加情報
    # clips配列の各要素にchannel名を付与
    clips_with_channel = []
    if isinstance(clip_urls, list):
        for c in clip_urls:
            c = dict(c)  # copy to avoid mutating original
            c['channel'] = channel_name
            clips_with_channel.append(c)
    result = {
        'chartData': chart_data,  # グラフ表示用（全データ）
        'totalComments': total_comments,
        'analyzedComments': analyzed_comments,  # クリップ生成に使用したコメント数
        'skippedIntroComments': intro_comments_count if skip_intro else 0,
        'graphs': graph_paths,
        'customEmojiStats': custom_emoji_stats,
        'video_url': video_url,
        'video_id': video_id,
        'title': video_title,
        'channel': channel_name,
        'clips': clips_with_channel if isinstance(clip_urls, list) else [],  # 必ずリスト型で返す
        'group_name': group_name,
        'group_id': group_id,
        'creator_eng': creator_eng,
        'method': 'partial_download',
        'avg_comments_per_minute': avg_comments_per_minute,
        'max_comments_10sec': max_comments_10sec,
        'statistics': {
            'total_comments': len(comments),
            'analyzed_comments': len(comments_with_scores),
            'multi_emotion_clips_found': len(clip_urls) if isinstance(clip_urls, list) else 0
        }
    }
    
    # プレミア公開の情報を追加
    if is_premiere:
        result['isPremiere'] = True
        result['countdownMinutes'] = countdown_minutes if countdown_minutes else 0
        result['premiereOffset'] = premiere_offset if premiere_offset else 0

    #サムネイルをDL
    thumbnail_path = download_thumbnail(video_url=video_url,channel_name=channel_name)
    
    # JSONサマリーにも出力
    try:
        export_to_json(result, comments, duration_minutes, metadata)
        print("✓ サマリーJSON出力完了")
    except Exception as e:
        print(f"✗ サマリーJSON出力エラー: {e}")

    # 配信者ごとサマリーも再構築（全動画から集計）
    try:
        build_streamer_summary_from_results()
        print("✓ 配信者ごとサマリーJSON出力完了")
    except Exception as e:
        print(f"✗ 配信者ごとサマリーJSON出力エラー: {e}")

    # Gemini一言コメントjsonをAPIレスポンスに含める
    gemini_comments_path = os.path.join('backend', 'data', 'gemini_comments', f'{video_id}.json')
    if os.path.exists(gemini_comments_path):
        with open(gemini_comments_path, 'r', encoding='utf-8') as f:
            gemini_comments = json.load(f)
            # クリップごとにgemini_commentsをclipsに紐付ける
            # clips: [{...clip info..., 'gemini_comments': ["一言1", "一言2", "一言3"]}, ...]
            if isinstance(result.get('clips'), list) and isinstance(gemini_comments, dict):
                for i, clip in enumerate(result['clips']):
                    rank = clip.get('rank') or clip.get('clip_rank')
                    key = str(rank) if rank is not None else None
                    if key in gemini_comments:
                        clip['gemini_comments'] = gemini_comments[key]
                    else:
                        clip['gemini_comments'] = []
                    # デバッグ出力
                    # print(f"[DEBUG] clip idx={i} rank={rank} key={key} gemini_comments={clip['gemini_comments']}")
            result['gemini_comments'] = gemini_comments
    else:
        # gemini_commentsがなければ空リストをclipsに付与
        if isinstance(result.get('clips'), list):
            for clip in result['clips']:
                clip['gemini_comments'] = []
        result['gemini_comments'] = {}
    
    # クリップシートを生成
    create_clip_sheet_from_process_video(result, video_id)
    print("✓ クリップシートを生成しました")

    return result

def generate_subs(video_url, video_id, combine_order=None):
    # --- クリップごとにWhisper字幕抽出 ---
    tmp_dir = os.path.join("backend", "clips", "tmp", f"{video_id}")
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
    all_subs_info = []
    for idx, clip in enumerate(combine_order):
        # クリップ区間内のコメント数を計算
        start_sec = clip.get('start_sec', 0)
        end_sec = clip.get('end_sec', 0)
        clip_rank = clip.get('rank', idx + 1)  # rankがない場合はidx+1を使用
        partial_clip_path = os.path.join(tmp_dir, f"{video_id}_clip_{clip_rank}.mp4")
        try:
            # partial_clip_pathが存在する場合はスキップ
            if os.path.exists(partial_clip_path):
                print(f"[INFO] 既に存在するクリップ: {partial_clip_path}")
            else:
                print(f"[INFO] クリップをダウンロード: {partial_clip_path}")
                # クリップの部分動画をダウンロード
                download_partial_video(
                    video_url,
                    start_seconds=start_sec,
                    end_seconds=end_sec,
                    output_path=partial_clip_path,
                    buffer_seconds=0
                )
            # Whisperで字幕抽出
            whisper_segments = run_whisper_on_video(partial_clip_path)
            # ASS用データ化
            style = {
                "font_name": "Arial",
                "font_size": 48,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "align": 2
            }
            ass_subs_data = whisper_segments_to_ass_data(whisper_segments, style)
            # クリップランク・start・end・textのみ抽出
            subs_info = [
                {
                    "clip_rank": clip_rank,
                    "start": sub["start"],
                    "end": sub["end"],
                    "text": sub["text"]
                }
                for sub in ass_subs_data
            ]
            # subs_infoは必要に応じて保存・利用
            clip["whisper_subs_info"] = subs_info
            all_subs_info.extend(subs_info)
        except Exception as e:
            print(f"[ERROR] Whisper字幕抽出失敗: {e}")
            import traceback
            traceback.print_exc()

    # 字幕シートを生成
    create_subs_sheet_from_process_video(all_subs_info, video_id)
    print("✓ 字幕シートを生成しました")

def regenerate_gemini_one_liner(channel_name, video_id, rank, base_dir='backend/', gemini_api_func=None):
    """
    指定rankのコメントのみでGemini一言を再生成し、パースして返す。
    gemini_api_func: (prompt_txt_path) -> gemini_output_path を実行する関数
    戻り値: [一言1, ...]（5件、なければ空文字で埋める）
    """
    # gemini_api_funcが未指定ならデフォルトをimport
    if gemini_api_func is None:
        from gemini_prompt_util import gemini_api_func as default_gemini_api_func
        gemini_api_func = default_gemini_api_func
    
    path = os.path.join(base_dir,'data','draw_comments', f"{video_id}.json")
    if not os.path.exists(path):
        print(f"[ERROR] draw_commentsファイルが見つかりません: {path}")
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            draw_comments = json.load(f)
    except Exception as e:
        print(f"[ERROR] draw_commentsファイルの読み込みに失敗: {e}")
        return []

    gemini_prompt_path, gemini_prompt_txt_path = regenerate_gemini_prompt_and_data(
        draw_comments, channel_name, video_id, rank, base_dir=f"{base_dir}/clips"
    )
    gemini_output_path = gemini_api_func(gemini_prompt_txt_path)
    one_liners = parse_gemini_output(gemini_output_path, rank)
    return one_liners

# 新しい結合関数: combine_clips_with_overlay_and_subs
def combine_clips_with_overlay_and_subs(
    video_url,
    group_id="hololive",
    combine_order=None,
    output_filename=None
):
    """
    指定クリップを指定順で結合し、各クリップにコメントオーバーレイ＋ASS字幕を付与して結合する。
    OP/アイキャッチ/EDも固定パスで自動挿入。
    SRT/字幕関連の処理は行わない。
    combine_order: [{start_sec, end_sec, rank, main_label, ...}, ...] のリスト

    Refactored: generate_clips_with_assとconcat_clips_with_eyecatchによる2段階処理に分割。
    """
    try:
        # group_idをcombine_orderから自動取得（全クリップ同じ前提）
        if combine_order and len(combine_order) > 0 and 'group_id' in combine_order[0]:
            group_id = combine_order[0]['group_id']
        # 1. クリップ生成＋ASS字幕合成
        print("[INFO] generate_clips_with_ass を実行します...")
        generate_result = generate_clips_with_ass(
            video_url=video_url,
            group_id=group_id,
            combine_order=combine_order
        )
        print("[DEBUG] generate_clips_with_ass 実行完了")
        if not generate_result or not generate_result.get('success'):
            print(f"[ERROR] generate_clips_with_ass 失敗: {generate_result.get('error') if generate_result else 'Unknown error'}")
            return None
        ass_clips = generate_result.get('clip_paths')
        clip_metadata = generate_result.get('clip_metadata')
        # import time（ファイル先頭でインポート済み）
        time.sleep(0.2)

        # OP動画生成（create_op_from_clips）
        original_video_paths = generate_result.get('original_video_paths')
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_op:
            op_temp_path = tmp_op.name
        create_op_from_clips(original_video_paths, op_temp_path, combine_order=combine_order)
        print(f"[DEBUG] OP動画一時ファイル生成: {op_temp_path}")

        print("[DEBUG] クリップ生成・ASS合成完了。次に結合処理へ進みます")
        # 2. OP/ED/アイキャッチとASS付きクリップを結合
        print("[INFO] concat_clips_with_eyecatch を実行します...")
        print(f"[DEBUG] ass_clips: {ass_clips}")
        # 必要な情報をgenerate_resultやcombine_orderから取得
        # channel_name, video_idはgenerate_resultのclip_metadataやcombine_orderから取得可能
        channel_name = None
        video_id = None
        if clip_metadata and len(clip_metadata) > 0:
            channel_name = clip_metadata[0].get('channel') if 'channel' in clip_metadata[0] else None
            video_id = clip_metadata[0].get('video_id') if 'video_id' in clip_metadata[0] else None
        if not channel_name or not video_id:
            # fallback: メタデータを再取得
            metadata = get_video_metadata(video_url)
            channel_name = metadata.get('channel', '')
            video_id = extract_video_id(video_url)

        print("[DEBUG] reached before ffmpeg command (concat_clips_with_eyecatch呼び出し直前)")
        output_video = concat_clips_with_eyecatch(
            video_paths=ass_clips,
            channel_name=channel_name,
            video_id=video_id,
            group_id=group_id,
            output_filename=output_filename,
            clip_metadata=clip_metadata,
            op_temp_path=op_temp_path
        )
        print("[DEBUG] concat_clips_with_eyecatch 実行完了")
        if not output_video:
            print(f"[ERROR] concat_clips_with_eyecatch 失敗: Noneが返されました")
            return None
        print(f"[INFO] 結合動画生成完了: {output_video}")
        # # --- 処理完了後に一時ディレクトリ削除 ---
        # tmp_dir = os.path.join('backend/clips/tmp', video_id)
        # if os.path.exists(tmp_dir):
        #     try:
        #         shutil.rmtree(tmp_dir)
        #         print(f"[DEBUG] deleted tmp dir: {tmp_dir}")
        #     except Exception as e:
        #         print(f"[ERROR] failed to delete tmp dir: {tmp_dir}, {e}")

        set_combine_flag_true(video_url)
        print(f"[DEBUG] 結合フラグをONにしました: {video_url}")
        return output_video
    except Exception as e:
        print(f"[ERROR] combine_clips_with_overlay_and_subs全体で例外発生: {e}")
        import traceback
        traceback.print_exc()
        return None
    
# === ショート動画生成本体関数（ステップ1：雛形・保存先パス生成） ===
def create_short_video(video_id, channel_name, start_time, end_time, title=None, rank=None, caption_text=None, score=None):
    """
    ショート動画生成本体（9:16＋上下モーションブラー＋コメント合成）
    Args:
        video_id (str): YouTube動画ID
        channel_name (str): チャンネル名
        start_time (float|str): クリップ開始時刻（秒またはhh:mm:ss）
        end_time (float|str): クリップ終了時刻（秒またはhh:mm:ss）
        title (str, optional): タイトルや説明
    Returns:
        dict: { 'success': bool, 'short_path': str, 'error': str (optional) }
    """
    try:
        # --- 保存先パス生成 ---
        channel_dir = sanitize_filename(channel_name)
        short_id = str(uuid.uuid4())[:8]
        save_dir = f"g:/マイドライブ/clips/{channel_dir}/{video_id}"
        clip_dir = os.path.join('backend', 'clips', channel_dir, video_id)
        os.makedirs(save_dir, exist_ok=True)

        # --- for_short_whispered_path探索ロジックを追加 ---
        tmp_dir = os.path.join('backend', 'clips', 'tmp', sanitize_filename(video_id))
        os.makedirs(tmp_dir, exist_ok=True)
        for_short_whispered_path = os.path.join(tmp_dir, f"{rank}_whispered_short.mp4")
        for_short_whispered_exists = os.path.exists(for_short_whispered_path)
        print(f"[DEBUG] for_short_whispered_path: {for_short_whispered_path} exists={for_short_whispered_exists}")

        # 一時ディレクトリ作成
        temp_dir = tempfile.mkdtemp()
        # 時間変換
        def time_to_seconds(t):
            if isinstance(t, (int, float)):
                return float(t)
            if isinstance(t, str):
                parts = t.split(":")
                if len(parts) == 3:
                    h, m, s = parts
                    return int(h)*3600 + int(m)*60 + float(s)
                elif len(parts) == 2:
                    m, s = parts
                    return int(m)*60 + float(s)
                else:
                    return float(parts[0])
            raise ValueError("Invalid time format")
        start_sec = time_to_seconds(start_time)
        end_sec = time_to_seconds(end_time)
        if start_sec >= end_sec:
            return {'success': False, 'error': 'start_time must be less than end_time'}

        if for_short_whispered_exists:
            # 既に存在する場合はそのパスを使用
            output_whispered_path= os.path.join(temp_dir, f"{video_id}_short_whispered.mp4")
            shutil.copy2(for_short_whispered_path, output_whispered_path)

            print(f"✅ 既存のWhisper処理済み動画を使用: {output_whispered_path}")
        else :
            print(f"[DEBUG] for_short_whispered_pathが存在しないため新規生成: {for_short_whispered_path}")
            # --- ステップ2: 部分ダウンロード処理 ---
            # video_id から YouTube 動画URLを生成（APIから渡す場合は video_url を引数に追加してもよい）
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            # 一時ディレクトリ作成
            temp_video_path = os.path.join(temp_dir, f"{video_id}_partial.mp4")

            # --- yt-dlpで部分ダウンロード（YouTube URLを直接ffmpegに渡さない） ---
            partial_result = download_partial_video(
                video_url, start_sec, end_sec, temp_video_path, buffer_seconds=0
            )
            if not partial_result or not partial_result.get('success'):
                shutil.rmtree(temp_dir)
                return {'success': False, 'error': f"部分ダウンロード失敗: {partial_result.get('error') if partial_result else 'unknown error'}"}
            print(f"✅ 部分ダウンロード成功: {temp_video_path}")

            # creator_styles.jsonから縁取り色取得
            styles_path = Path('backend') / 'data' / 'creator_styles.json'
            outline_color = '&H00000000'
            if channel_name:
                try:
                    with open(styles_path, encoding='utf-8') as f:
                        styles = json.load(f)
                    outline_color = styles.get(sanitize_filename(channel_name), {}).get('outline_color', outline_color)
                    print(f"[DEBUG] outline_color for {channel_name}: {outline_color}")
                except Exception as e:
                    print(f"[WARN] creator_styles.json読み込み失敗: {e}")

            # Whisper字幕スタイル
            subtitle_style = {
                "font_name": "ラノベPOP v2",
                "font_size": 120,
                "font_color": "&H00FFFFFF",
                "outline_color": outline_color,
                "align": 2,
            }

            ass_path = os.path.join(temp_dir, f"{video_id}_short_whisper.ass")
            output_whispered_path = os.path.join(temp_dir, f"{video_id}_short_whispered.mp4")
            try:
                create_ass_from_whisper(temp_video_path, ass_path, subtitle_style, model_size="large", language="ja")
                combine_video_and_ass(temp_video_path, ass_path, output_whispered_path)
                print(f"✅ Whisper処理成功: {output_whispered_path}")
            except Exception as e:
                import traceback
                print(f"[ERROR] Whisper字幕生成・合成失敗: {e}")
                traceback.print_exc()

        # --- ステップ3: 9:16キャンバス＋上下モーションブラー背景生成 ---
        temp_9x16_path = os.path.join(temp_dir, "temp_9x16.mp4")
        # ffmpeg filter_complex例:
        # - 入力: 1280x720 (16:9) → 出力: 1080x1920 (9:16)
        # - 背景: 元動画を1080x1920に拡大→ガウスブラー
        # - 前景: 元動画を中央1080x608にリサイズ→中央配置
        # アスペクト比維持で中央に配置、上下ブラー背景
        filter_complex = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:1[bg];"
            "[0:v]scale=1080:608:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2[fg];"
            "[bg][fg]overlay=0:656"
        )
        blur_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loglevel", "error",
            "-i", output_whispered_path,
            "-filter_complex", filter_complex,
            "-r", "30",  # 明示的に30fpsに固定
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            temp_9x16_path
        ]
        try:
            result2 = subprocess.run(blur_cmd, capture_output=True, text=True)
            if result2.returncode != 0:
                shutil.rmtree(temp_dir)
                return {'success': False, 'error': f'9:16変換/ブラー失敗: {result2.stderr}'}
        except Exception as e:
            shutil.rmtree(temp_dir)
            return {'success': False, 'error': f'9:16変換/ブラー例外: {str(e)}'}
        print(f"✅ 9:16変換＋ブラー成功: {temp_9x16_path}")
        
        # --- ステップ4: コメントデータ抽出・整形（draw_commentsから間引き＋タイムスタンプ補正） ---
        comment_json_path = f"backend/data/draw_comments/{video_id}.json"

        def load_comments_for_clip(json_path, target_rank, clip_start):
            with open(json_path, encoding='utf-8') as f:
                all_comments = json.load(f)
            # 'clip_rank' キーでフィルタ（型を揃えて比較）
            def normalize_rank(val):
                if val in (None, '', 'None'):
                    return None
                return str(val).split('.')[0]

            filtered = [
                c for c in all_comments
                if normalize_rank(normalize_rank(c.get('clip_rank'))) == normalize_rank(target_rank)
            ]
            if not filtered:
                return []
            # 4つに1つだけ採用
            if len(filtered) > 35*4:
                filtered = filtered[::4]
            # timestampをクリップ内相対時刻に変換
            for c in filtered:
                c['timestamp'] = c['timestamp'] - clip_start
            return filtered

        # clip_rankはstart_secで一意に決まる前提（必要に応じて修正）
        clip_rank = str(rank)
        # デバック用
        print(f"clip_rank: {clip_rank}")
        comments = load_comments_for_clip(comment_json_path, clip_rank, start_sec)

        from comment_rendering import EmojiProcessor
        emoji_processor = EmojiProcessor()
        # 絵文字キャッシュ・プロセッサ（必要に応じて本物/ダミーを選択）
        emoji_dict_path = f"backend/clips/emoji_dict/{sanitize_filename(channel_name)}.json"
        if os.path.exists(emoji_dict_path):
            with open(emoji_dict_path, encoding='utf-8') as f:
                emoji_dict = json.load(f)
        else:
            emoji_dict = {}
        for idx, c in enumerate(comments):
            c['area'] = 'top' if idx % 2 == 0 else 'bottom'
            c['elements'] = emoji_processor.parse_comment_elements(c['text'], emoji_dict)
        emoji_cache = emoji_processor.download_and_cache_emojis(emoji_dict, channel_name)
        # --- ここまでで comments に「5つに1つ間引き＋タイムスタンプ補正済み」コメントリストが入る ---
        # --- ステップ5: レーン割り当て・パラメータ計算・オーバーレイ生成 ---
        from comment_rendering import assign_comment_lanes_9x16, VideoProcessor9x16, EmojiProcessor

        # レーン数・スペース比率
        top_lanes = 4
        bottom_lanes = 4
        video_width, video_height = 1080, 1920
        center_height = int(video_width * 9 / 16)
        area_ratio = ((video_height - center_height) / 2) / video_height

        # レーン割り当て
        comments_with_lanes = assign_comment_lanes_9x16(comments, top_lanes=top_lanes, bottom_lanes=bottom_lanes)

        # 文字サイズ自動計算
        lane_height = int((video_height * area_ratio) / top_lanes)
        font_size = int(lane_height * 0.55)  # 文字サイズを小さめに調整        

        # フレーム数・fps
        fps = 30
        duration = end_sec - start_sec
        frame_count = int(duration * fps)

        # フレーム画像生成
        processor_9x16 = VideoProcessor9x16(temp_dir)
        # 9:16用の絵文字サイズ倍率を指定
        emoji_scale = 4.0  # 必要に応じて倍率を調整
        ok = processor_9x16.generate_frame_images_9x16(
            comments_with_lanes, emoji_cache, frame_count, fps,
            video_width=video_width, video_height=video_height,
            channel_name=channel_name, emoji_processor=emoji_processor,
            font_size=font_size, top_lanes=top_lanes, bottom_lanes=bottom_lanes,
            top_area_ratio=area_ratio, bottom_area_ratio=area_ratio,
            emoji_scale=emoji_scale
        )
        if not ok:
            shutil.rmtree(temp_dir)
            return {'success': False, 'error': 'コメントオーバーレイ画像生成失敗'}

        # 動画＋オーバーレイ合成
        overlayed_path = os.path.join(temp_dir, "short_overlayed.mp4")
        frame_pattern = os.path.join(temp_dir, "%06d.png")
        ffmpeg_overlay_cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", temp_9x16_path,
            "-framerate", str(fps), "-i", frame_pattern,
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-shortest",
            overlayed_path
        ]
        result3 = subprocess.run(ffmpeg_overlay_cmd, capture_output=True, text=True)
        if result3.returncode != 0:
            shutil.rmtree(temp_dir)
            return {'success': False, 'error': f'コメント合成失敗: {result3.stderr}'}
        print(f"✅ コメントオーバーレイ合成成功: {overlayed_path}")
        # --- ステップ3.5: 一言ASS字幕生成・合成（caption_textがあれば） ---
        final_video_path = overlayed_path
        print(f"[DEBUG] caption_text: {caption_text}")
        if caption_text:
            try:
                ass_path = os.path.join(clip_dir, "caption.ass")
                subtitle_data = [{
                    'text': caption_text,
                    'start': 0,
                    'end': min(15, end_sec - start_sec),  # 15秒 or クリップ長
                    'align': 8,  # 上部中央
                    'font_size': 120,
                    'font_color': '&H00FFFFFF',
                    'outline_color': '&H00FFD288',
                    'pos': '540,280',
                    'outline_width': 30
                }]
                create_ass_file_9x16(subtitle_data, ass_path, creator_name='system', style={
                    'font_name': 'ラノベPOP v2',
                    'outline_width': 30,
                    'font_color': '&H00FFFFFF',
                    'outline_color': '&H00FFD288',
                })
                # ASS字幕を合成
                ass_output_path = os.path.join(temp_dir, "with_caption.mp4")
                try:
                    combine_video_and_ass(final_video_path, ass_path, ass_output_path)
                    print(f"✅ ASS字幕合成成功: {ass_output_path}")
                except Exception as e:
                    print(f"[ERROR] combine_video_and_ass失敗: {e}")
                    import traceback
                    traceback.print_exc()
                    raise

                # グラフを合成(add_sliding_graphs_to_videoを用いて、グラフを合成)
                sanitized_channel = sanitize_filename(channel_name)
                graph_image_path = os.path.join(clip_dir, "combined_all_graph.png")
                if not os.path.exists(clip_dir):
                    os.makedirs(clip_dir, exist_ok=True)
                slide_output_path = os.path.join(clip_dir, f"short_with_sliding_graphs.mp4")
                try:
                    add_sliding_graphs_to_video(input_video_path=ass_output_path, graphs_image_path=graph_image_path, output_video_path=slide_output_path)
                    final_video_path = slide_output_path
                    print(f"✅ スライドグラフ合成成功: {slide_output_path}")
                except Exception as e:
                    print(f"[ERROR] add_sliding_graphs_to_video失敗: {e}")
                    import traceback
                    traceback.print_exc()
                    raise
            except Exception as e:
                print(f"[ERROR] caption_text処理全体で例外: {e}")
                import traceback
                traceback.print_exc()
                raise

        # --- ステップ5: 完成動画を保存先に移動 ---
        short_filename = f"short__{caption_text}.mp4"
        short_path = os.path.join(save_dir, short_filename)
        shutil.move(final_video_path, short_path)
        shutil.rmtree(temp_dir)
        
        # # --- 処理完了後に一時ディレクトリ削除 ---
        # tmp_dir = os.path.join('backend/clips/tmp', video_id)
        # if os.path.exists(tmp_dir):
        #     try:
        #         shutil.rmtree(tmp_dir)
        #         print(f"[DEBUG] deleted tmp dir: {tmp_dir}")
        #     except Exception as e:
        #         print(f"[ERROR] failed to delete tmp dir: {tmp_dir}, {e}")
        print(f"✅ ショート動画生成成功: {short_path}")
        return {'success': True, 'short_path': short_path}
    except Exception as e:
        return {'success': False, 'error': str(e)}

