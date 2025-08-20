import os
from utility import sanitize_filename, extract_video_id, format_srt_timestamp
from comment_processor import get_comments_for_timerange
from youtube_handler import get_video_metadata
from file_io import generate_clip_urls_txt
from comment_processor import calculate_max_comments_per_interval

def add_metadata_to_clips(final_clips, video_url, comments, excitement_df_full=None):
    from utility import extract_video_id
    from datetime import timedelta
    video_id = extract_video_id(video_url)
    url_base = f"https://www.youtube.com/watch?v={video_id}"
    score_labels = ['laugh', 'healing', 'chaos']
    for idx, c in enumerate(final_clips):
        cmt_in_clip = [cm for cm in comments if c['start'] <= cm.get('timestamp',0) <= c['end']]
        c['comment_count'] = len(cmt_in_clip)
        c['url'] = f"{url_base}&t={int(c['start'])}s"
        c['start_time'] = str(timedelta(seconds=int(c['start'])))
        c['end_time'] = str(timedelta(seconds=int(c['end'])))
        c['rank'] = idx+1
        if 'scores' not in c or not isinstance(c['scores'], dict):
            c['scores'] = {}
        if excitement_df_full is not None:
            mask = (excitement_df_full['start_time'] < c['end']) & (excitement_df_full['end_time'] > c['start'])
            for label in score_labels:
                col = f'{label}_score'
                if col in excitement_df_full.columns:
                    sum_val = excitement_df_full.loc[mask, col].sum() if not excitement_df_full.loc[mask, col].empty else 0
                    c['scores'][label] = float(sum_val)
        for label in score_labels:
            if label not in c['scores']:
                c['scores'][label] = 0
        if excitement_df_full is not None:
            for label in score_labels:
                col = f'{label}_score'
                if col in excitement_df_full.columns:
                    mask = (excitement_df_full['start_time'] < c['end']) & (excitement_df_full['end_time'] > c['start'])
                    max_val = excitement_df_full.loc[mask, col].max() if not excitement_df_full.loc[mask, col].empty else 0
                    if 'window_score' not in c:
                        c['window_score'] = c['scores'].get(label, 0) if isinstance(c.get('scores'), dict) else 0
                    if 'max_scores' not in c or not isinstance(c['max_scores'], dict):
                        c['max_scores'] = {}
                    c['max_scores'][label] = float(max_val) if max_val is not None else 0.0
    return final_clips if isinstance(final_clips, list) else []

def generate_video_statistics_txt(comments, video_url, duration_minutes=None, output_dir='backend/clips', channel_name='', excitement_periods=''):
    """
    動画統計情報をTXTファイルに出力
    - 合計コメント数
    - アーカイブ時間（自動取得）
    - 最大瞬間コメント数(10秒当たり)
    - 平均コメント数(1分当たり)
    """
    try:
        if duration_minutes is None or duration_minutes <= 0:
            metadata = get_video_metadata(video_url)
            video_duration_seconds = metadata.get('duration', 0)
            if video_duration_seconds > 0:
                duration_minutes = video_duration_seconds / 60
                # print(f"動画時間を自動取得: {duration_minutes:.2f}分 ({video_duration_seconds}秒)")
            else:
                print("警告: 動画時間を取得できませんでした。デフォルト値（30分）を使用します。")
                duration_minutes = 30
        else:
            print(f"動画時間（手動指定）: {duration_minutes}分")
        metadata = get_video_metadata(video_url)
        video_title = metadata.get('title', '')
        txt_filename = f'{sanitize_filename(video_title)}.txt'
        video_id = extract_video_id(video_url)
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
        total_comments = len(comments)
        duration_seconds = duration_minutes * 60
        max_comments_per_10sec = calculate_max_comments_per_interval(comments, duration_seconds, 10)
        avg_comments_per_minute = total_comments / duration_minutes if duration_minutes > 0 else 0
        total_seconds = int(duration_minutes * 60)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        duration_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        excitement_periods_sorted = sorted(excitement_periods, key=lambda x: x['max_score'], reverse=False)
        other_time=22
        total_time=other_time
        for i, period in enumerate(excitement_periods_sorted[:-1]):
            clip_duration = int(period['end'] - period['start'])
            total_time += clip_duration
        hours2 = total_time // 3600
        minutes2 = (total_time % 3600) // 60
        seconds2 = total_time % 60
        duration_formatted2 = f"{hours2:02d}:{minutes2:02d}:{seconds2:02d}"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("ご視聴ありがとうございます！\n")
            f.write("いいね、チャンネル登録お願いします！\n")
            f.write(f"1位のクリップはこちら→{duration_formatted2}\n\n\n")
            f.write("動画統計情報\n")
            f.write("=" * 30 + "\n\n")
            f.write(f"アーカイブ時間: {duration_formatted}\n")
            f.write(f"合計コメント数: {total_comments:,} 件\n")
            f.write(f"最大コメント数: {max_comments_per_10sec} 件/10秒\n")
            f.write(f"平均コメント数: {avg_comments_per_minute:.1f} 件/分\n\n")
            f.write(f"{duration_formatted}\n")
            f.write(f"{total_comments:,} 件\n")
            f.write(f"{max_comments_per_10sec} 件/10秒\n")
            f.write(f"{avg_comments_per_minute:.1f} 件/分\n")
        # print(f"動画統計情報を出力: {txt_path}")
        return {"success": True, "file_path": txt_path, "duration_minutes": duration_minutes}
    except Exception as e:
        print(f"動画統計出力エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

def generate_clip_comments_txt(excitement_periods, video_url, output_dir='backend/clips', channel_name=''):
    """
    各クリップ内のコメント統計情報をSRTファイルに出力
    """
    from datetime import timedelta
    try:
        srt_filename = 'clip_statistics.srt'
        video_id = extract_video_id(video_url)
        if not video_id:
            return {"error": "無効な動画URLです"}
        if channel_name:
            channel_dir = os.path.join(output_dir, sanitize_filename(channel_name))
            video_specific_dir = os.path.join(channel_dir, video_id)
            if not os.path.exists(channel_dir):
                os.makedirs(channel_dir, exist_ok=True)
            if not os.path.exists(video_specific_dir):
                os.makedirs(video_specific_dir, exist_ok=True)
            srt_path = os.path.join(video_specific_dir, srt_filename)
        else:
            srt_path = os.path.join(output_dir, srt_filename)
        excitement_periods_sorted = sorted(excitement_periods, key=lambda x: x['max_score'], reverse=False)
        current_time = 0
        srt_lines = []
        for i, period in enumerate(excitement_periods_sorted):
            rank = len(excitement_periods_sorted) - i
            clip_duration = int(period['end'] - period['start'])
            # 既にperiodにcomment_countが含まれていればそれを使う。なければ従来通り計算
            if 'comment_count' in period:
                comment_count = period['comment_count']
                clip_comments = period.get('comments', [])
            else:
                # print(f"クリップ#{rank}のコメントを取得中...")
                clip_comments = get_comments_for_timerange(
                    video_url, 
                    period['start'], 
                    period['end']
                )
                comment_count = len(clip_comments)
                period['comments'] = clip_comments
            start_time = current_time
            end_time = start_time + 8
            start_str = format_srt_timestamp(start_time)
            end_str = format_srt_timestamp(end_time)
            text = (
                f" # {rank}（ {comment_count}件 / {clip_duration}秒 ）\n"
                f" 盛り上がりスコア: {period['max_score']:.2f}\n"
                f" コメント密度: {comment_count / clip_duration:.2f}件/秒"
            )
            srt_lines.append(f"{i + 1}\n{start_str} --> {end_str}\n{text}\n")
            current_time += clip_duration
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_lines))
        # print(f"クリップ統計SRT情報を出力: {srt_path}")
        return {"success": True, "file_path": srt_path}
    except Exception as e:
        print(f"クリップコメント出力エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# === analyzer.pyから移動: save_per_second_scores ===
import os
import json
def save_per_second_scores(excitement_df, video_id):
    if excitement_df is None or len(excitement_df) == 0:
        return
    per_sec = {}
    for idx, row in excitement_df.iterrows():
        start = int(row.get('start_time', 0))
        end = int(row.get('end_time', 0))
        for t in range(start, end):
            per_sec[int(t)] = {
                'timestamp': int(t),
                'laugh_score': float(row.get('laugh_score', 0)),
                'healing_score': float(row.get('healing_score', 0)),
                'chaos_score': float(row.get('chaos_score', 0)),
                'comment_count': int(row.get('comment_count', 0)),
            }
    out_dir = os.path.join('backend', 'data', 'scores')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'{video_id}_scores.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(list(per_sec.values()), f, ensure_ascii=False, indent=2)

def generate_all_txt_files(video_url, comments, excitement_periods, duration_minutes, video_title='', channel_name=''):
    """
    3つのTXTファイルをすべて生成する統合関数
    """
    results = {}
    # print("動画統計情報を生成中...")
    stats_result = generate_video_statistics_txt(comments, video_url, channel_name=channel_name, excitement_periods=excitement_periods)
    results['video_statistics'] = stats_result
    # print("クリップ統計字幕情報を生成中...")
    comments_result = generate_clip_comments_txt(excitement_periods, video_url, channel_name=channel_name)
    results['clip_comments'] = comments_result
    return results
