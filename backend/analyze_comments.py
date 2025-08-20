def extract_top_windows(df, score_col, window_size=10, top_n=100, min_start=None, max_end=None):
    arr = df[score_col].values
    starts = [int(x) for x in df['start_time'].values]
    ends = [int(x) for x in df['end_time'].values]
    n = len(arr)
    window_scores = []
    for i in range(n - window_size + 1):
        s = int(starts[i])
        e = int(ends[i + window_size - 1])
        if (min_start is not None and s < min_start) or (max_end is not None and e > max_end):
            continue
        total = float(arr[i:i+window_size].sum())
        window_scores.append((s, e, total))
    window_scores = sorted(window_scores, key=lambda x: x[2], reverse=True)[:top_n]
    return window_scores

def ensure_top3_per_emotion(multi_emotion_result, min_start_seconds, max_end_seconds, total_seconds, multi_stage_timewise_merge, extract_best_subclip, excitement_df_full):
    result = []
    label_jp_map = {'laugh': '爆笑指数', 'healing': 'かわいさ指数', 'chaos': '盛り上がり指数'}
    for label in ['laugh', 'healing', 'chaos']:
        label_clips = []
        for p in multi_emotion_result[label]:
            start = max(p[0] - 15, min_start_seconds, 0)
            video_end = max_end_seconds if max_end_seconds is not None else total_seconds
            if video_end is not None:
                end = min(p[1] + 3, video_end)
            else:
                end = p[1] + 3
            duration = end - start
            start = max(start, min_start_seconds)
            if max_end_seconds is not None:
                end = min(end, max_end_seconds)
                duration = end - start
            label_clips.append({
                'start': start, 'end': end, 'labels': [label], 'scores': {label: p[2]}, 'main_label': label, 'duration': duration, 'window_score': p[2]
            })
        label_clips.sort(key=lambda x: x['scores'].get(label, 0), reverse=True)
        merged_label_clips = multi_stage_timewise_merge(label_clips, label)
        score_col = f'smoothed_{label}_score' if f'smoothed_{label}_score' in excitement_df_full.columns else f'{label}_score'
        score_series = excitement_df_full.set_index('start_time')[score_col]
        subclip_debugs = []
        new_merged = []
        for c in merged_label_clips:
            if c['end'] - c['start'] > 35:
                c2 = extract_best_subclip(c, score_series, label, subclip_length=35, smooth_window=5, debug=True)
                subclip_debugs.append(c2.get('subclip_debug', {}))
                new_merged.append(c2)
            else:
                new_merged.append(c)
        merged_label_clips = new_merged
        sorted_by_score = sorted(merged_label_clips, key=lambda x: x['scores'].get(label, 0), reverse=True)
        for c in sorted_by_score[:5]:
            result.append({**c, 'main_label': label})
        if len([x for x in result if x['main_label']==label]) < 5:
            candidates = []
            for p in multi_emotion_result[label]:
                start = max(p[0] - 15, min_start_seconds, 0)
                video_end = max_end_seconds if max_end_seconds is not None else total_seconds
                if video_end is not None:
                    end = min(p[1] + 3, video_end)
                else:
                    end = p[1] + 3
                duration = end - start
                start = max(start, min_start_seconds)
                if max_end_seconds is not None:
                    end = min(end, max_end_seconds)
                    duration = end - start
                candidates.append({
                    'start': start, 'end': end, 'labels': [label], 'scores': {label: p[2]}, 'main_label': label, 'duration': duration, 'window_score': p[2]
                })
            candidates.sort(key=lambda x: x['scores'].get(label, 0), reverse=True)
            for c in candidates:
                if len([x for x in result if x['main_label']==label]) >= 5:
                    break
                result.append(c)
    result.sort(key=lambda x: (['laugh','healing','chaos'].index(x['main_label']), -x['scores'].get(x['main_label'],0), x['start']))
    return result
def debug_print_top3_clips(label, top3_clips):
    label_jp_map = {'laugh': '爆笑指数', 'healing': 'かわいさ指数', 'chaos': '盛り上がり指数'}
    label_jp = label_jp_map.get(label, label)
    print(f"[top3] {label_jp} トップ3クリップ（選択されたクリップ）:")
    for i, clip in enumerate(top3_clips):
        if clip is None:
            print(f"  #{i+1}: クリップなし")
            continue
        s = int(clip['start']) if clip.get('start') is not None else 'N/A'
        e = int(clip['end']) if clip.get('end') is not None else 'N/A'
        dur = (int(clip['end']) - int(clip['start'])) if clip.get('start') is not None and clip.get('end') is not None else 'N/A'
        max_score = clip['scores'][label] if 'scores' in clip and label in clip['scores'] else None
        subclip_info = ""
        if 'subclip_debug' in clip:
            subclip = clip['subclip_debug']
            subclip_info = f" | サブクリップ: {subclip.get('best_window', '')} スコア={subclip.get('best_score', '')}"
        print(f"  #{i+1}: {s}秒～{e}秒（{dur}秒間） 最大スコア={max_score}{subclip_info}")

import re
import numpy as np
import pandas as pd
from collections import defaultdict, Counter
from datetime import timedelta

# For subclip extraction
from scipy.signal import find_peaks

def extract_best_subclip(clip, score_series, label, subclip_length=35, smooth_window=5, debug=False):
    """
    マージ済みのクリップ辞書（'start', 'end'を含む）と、1秒ごとのスコア系列（pd.Series, index=秒）を受け取り、
    ピーク検出とスコアリングを用いて、最大subclip_length秒の最良サブクリップを抽出します。
    'start', 'end', 'duration'、およびデバッグ情報を含む新しい辞書を返します。
    """
    start = int(float(clip['start']))
    end = int(float(clip['end']))
    if end - start <= subclip_length:
        # カット不要の場合
        if debug:
            print(f"[subclip] カット不要: {int(start)}-{int(end)} ({int(end)-int(start)}秒)")
        return {**clip, 'subclip_debug': {'reason': 'no_cut', 'orig_start': int(start), 'orig_end': int(end)}}

    # この区間のスコア系列を抽出
    interval_scores = score_series.loc[int(start):int(end)-1] if end > start else score_series.loc[int(start):int(start)]
    # スコア系列を平滑化
    smoothed = interval_scores.rolling(window=smooth_window, min_periods=1, center=True).mean()
    # ピーク検出
    peaks, _ = find_peaks(smoothed.values)
    if len(peaks) == 0:
        # ピークが見つからない場合は最大値を使用
        peak_idx = int(np.argmax(smoothed.values))
        peaks = [peak_idx]
    best_score = -np.inf
    best_window = (start, start+subclip_length)
    best_peak = None
    debug_windows = []
    for peak in peaks:
        peak_time = int(start) + int(peak)
        win_start = max(int(start), int(peak_time) - 25)
        win_end = min(int(end), int(win_start) + subclip_length)
        win_start = max(int(start), int(win_end) - subclip_length)  # 終端付近の調整
        idx_start = int(win_start) - int(start)
        idx_end = int(win_end) - int(start)
        window_scores = smoothed.values[idx_start:idx_end]
        window_sum = float(np.sum(window_scores))
        window_max = float(np.max(window_scores))
        window_peaks = int(np.sum((window_scores == window_max)))
        score = window_sum + 0.5 * window_max + 0.1 * window_peaks
        debug_windows.append({'win_start': int(win_start), 'win_end': int(win_end), 'window_sum': window_sum, 'window_max': window_max, 'score': score})
        if score > best_score:
            best_score = score
            best_window = (int(win_start), int(win_end))
            best_peak = int(peak_time)
    new_clip = {**clip}
    new_clip['start'] = int(best_window[0])
    new_clip['end'] = int(best_window[1])
    new_clip['duration'] = int(best_window[1]) - int(best_window[0])
    new_clip['subclip_debug'] = {
        'orig_start': int(start), 'orig_end': int(end), 'best_peak': int(best_peak) if best_peak is not None else None,
        'best_window': (int(best_window[0]), int(best_window[1])), 'best_score': float(best_score), 'windows': debug_windows
    }
    if debug:
        print(f"[subclip] {label}: 元=({int(start)}-{int(end)}), 選択=({int(best_window[0])}-{int(best_window[1])}) スコア={float(best_score)}")
    return new_clip

def debug_print_top3_clips(label, top3_clips):
    """
    各ラベルごとに選ばれたトップ3クリップの情報を日本語で表示します。
    クリップがNoneの場合も考慮します。
    """
    print(f"[top3] {label} トップ3クリップ:")
    for i, clip in enumerate(top3_clips):
        if clip is None:
            print(f"  #{i+1}: クリップなし")
            continue
        s = int(clip['start']) if clip.get('start') is not None else 'N/A'
        e = int(clip['end']) if clip.get('end') is not None else 'N/A'
        dur = (int(clip['end']) - int(clip['start'])) if clip.get('start') is not None and clip.get('end') is not None else 'N/A'
        max_score = clip['scores'][label] if 'scores' in clip and label in clip['scores'] else None
        print(f"  #{i+1}: {s}秒～{e}秒（{dur}秒間） 最大スコア={max_score}")

def analyze_comment_content(comments):
    """コメント内容を分析（カスタム絵文字対応版）"""
    positive_keywords = ['草', '笹', 'わろた', 'すごい', 'やばい', '天才', 'うまい', '最高', 
                         'すげー', 'すげえ', '神', 'ええやん', 'おもろい', 'おもしろい', 'かわいい','可愛い','kusa']
    laugh_keywords = ['草', 'w', 'ｗ', 'わろた', 'おもろい', 'おもしろい', 'kusa']
    healing_keywords = [ 'えっっ','エッッ','ｴｯｯ','かわいい', '可愛い', 'KAWAII', 'てぇてぇ', '助かる','たすかる','尊い', '好き', 'love']  
    chaos_keywords = ['カオス', 'やば', '大惨事', 'あっ、', 'あっ。', 'あっ.']  
    laugh_keywords_en = [
    'lol', 'lmao', 'rofl', 'haha', 'hahaha', 'funny',
    'dead', 'i’m dead', '😭😭😭', 'xd', 'kek', 'this killed me',
    'too funny', 'I can’t', 'bruh', 'he’s so dumb', 'she’s so dumb'
    ]
    healing_keywords_en = [
        'cute', 'so cute', 'kawaii', 'adorable', 'precious', 'wholesome',
        'my heart', 'i’m crying', 'so sweet', 'angel', 'baby girl', 'uwu',
        'soft', 'protect her', 'too pure', 'she’s so cute', 'i love her'
    ]
    chaos_keywords_en = [
    'chaos', 'wtf', 'what just happened', 'what was that',
    'bro', 'omg', 'help', 'this is insane', 'crazy',
    'why', 'what the hell', 'im losing it', 'this stream is wild',
    'she’s unhinged', 'uncontrollable', 'insanity'
    ]



    emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)
    for comment in comments:
        score = 0
        laugh_score = 0
        healing_score = 0
        chaos_score = 0
        text = comment['text'].lower()

        # 爆笑指数（従来通りキーワード一致数で加算）
        for keyword in laugh_keywords:
            laugh_score += text.count(keyword)


        # "ポエム"が含まれていたらhealing_scoreを0点にする
        if "ポエム" in text:
            healing_score = 0
        else:
            # かわいさ指数（キーワード一致数で加算）
            for keyword in healing_keywords:
                healing_score += text.count(keyword)

        # "おつ"が含まれていたらchaos_scoreを0点にする
        if "おつ" in text:
            chaos_score = 0
        else:
            # 盛り上がり指数：!,?,！,？の合計数＋指定文字の連続最大数＋キーワード一致数
            symbol_chars = '!?,！？'
            symbol_count = sum(text.count(s) for s in symbol_chars)

            # 文字の連続（"あいうえおぁぃぅぇぉ"）の最大連続数
            chaos_vowel_chars = 'あいうえおぁぃぅぇぉaiueohlgy'
            max_chaos_vowel_run = 0
            current_chaos_vowel = ''
            current_chaos_run = 0
            for c in text:
                if c in chaos_vowel_chars:
                    if c == current_chaos_vowel:
                        current_chaos_run += 1
                    else:
                        current_chaos_vowel = c
                        current_chaos_run = 1
                    if current_chaos_run > max_chaos_vowel_run:
                        max_chaos_vowel_run = current_chaos_run
                else:
                    current_chaos_vowel = ''
                    current_chaos_run = 0
            # キーワード一致数も加算
            chaos_keyword_count = 0
            for keyword in chaos_keywords:
                chaos_keyword_count += text.count(keyword)
            chaos_score += symbol_count + max_chaos_vowel_run + chaos_keyword_count
        # positive_scoreは従来通り
        for keyword in positive_keywords:
            if keyword in text:
                score += 1
        # 'w'や'ｗ'は上記countで全てカバーされるので、ここは不要
        emoji_count = len(emoji_pattern.findall(text))
        # score += emoji_count  # 絵文字はスコアに加算しない
        # laugh_score += emoji_count // 2  # 絵文字はスコアに加算しない
        if comment.get('has_custom_emoji'):
            custom_emoji_count = len(comment.get('custom_emojis', []))
            score += custom_emoji_count * 0
        comment['positive_score'] = score
        comment['laugh_score'] = laugh_score
        comment['healing_score'] = healing_score
        comment['chaos_score'] = chaos_score
    return comments

def analyze_custom_emojis(comments):
    """カスタム絵文字の使用統計を分析"""
    emoji_counter = Counter()
    emoji_details = {}
    for comment in comments:
        for emoji in comment.get('custom_emojis', []):
            shortcut = emoji['shortcut']
            emoji_counter[shortcut] += 1
            if shortcut not in emoji_details:
                emoji_details[shortcut] = {
                    'id': emoji['id'],
                    'image_url': emoji.get('image_url'),
                    'first_used': comment['timestamp']
                }
    top_emojis = []
    for shortcut, count in emoji_counter.most_common(10):
        top_emojis.append({
            'shortcut': shortcut,
            'count': count,
            'image_url': emoji_details[shortcut]['image_url']
        })
    return {
        'total_custom_emojis': sum(emoji_counter.values()),
        'unique_custom_emojis': len(emoji_counter),
        'top_emojis': top_emojis
    }

# === analyzer.pyから移動: multi_stage_timewise_merge, merge_highlight_periods, smooth_scores, extract_top_windows ===
import numpy as np
def multi_stage_timewise_merge(clips, label):
    if not clips:
        return []
    # スコア履歴を準備
    for c in clips:
        if 'score_history' not in c:
            c['score_history'] = [c['scores'].get(label, 0)]
    # 時間順にソート
    clips = sorted(clips, key=lambda x: x['start'])
    merged = []
    i = 0
    while i < len(clips):
        current = clips[i].copy()
        score_hist = current.get('score_history', [current['scores'].get(label, 0)])
        j = i + 1
        while j < len(clips):
            next_clip = clips[j]
            # 重複・隣接していればマージ
            if next_clip['start'] <= current['end']:
                # 区間拡張
                current['end'] = max(current['end'], next_clip['end'])
                current['start'] = min(current['start'], next_clip['start'])
                # スコア履歴統合
                score_hist += next_clip.get('score_history', [next_clip['scores'].get(label, 0)])
                current['score_history'] = score_hist
                # ラベル統合
                current['labels'] = sorted(list(set(current['labels'] + next_clip.get('labels', []))))
                current['duration'] = current['end'] - current['start']
                # 他属性も必要に応じて統合
                j += 1
            else:
                break
        # マージ後のスコアは最大値
        current['scores'][label] = max(score_hist)
        if 'score_history' in current:
            del current['score_history']
        merged.append(current)
        i = j
    return merged

def merge_highlight_periods(periods, min_duration_seconds=10, max_duration_seconds=40, merge_margin=10):
    merged_periods = []
    if not periods:
        return []
    periods_for_merge = [p.copy() for p in periods]
    periods_for_merge.sort(key=lambda x: x['start'])
    current_period = None
    for period in periods_for_merge:
        if current_period is None:
            current_period = period.copy()
        elif period['start'] <= current_period['end'] + merge_margin:
            current_period['end'] = max(current_period['end'], period['end'])
            if period.get('max_score', 0) > current_period.get('max_score', 0):
                current_period['max_score'] = period['max_score']
                current_period['best_score_time'] = period.get('best_score_time', current_period.get('best_score_time'))
            if 'comments' in current_period and 'comments' in period:
                current_period['comments'].extend(period['comments'])
        else:
            duration = current_period['end'] - current_period['start']
            if duration >= min_duration_seconds:
                if duration > max_duration_seconds:
                    center = current_period.get('best_score_time', (current_period['start'] + current_period['end'])/2)
                    new_start = center - max_duration_seconds / 2
                    new_end = center + max_duration_seconds / 2
                    if new_start < current_period['start']:
                        new_start = current_period['start']
                        new_end = new_start + max_duration_seconds
                    elif new_end > current_period['end']:
                        new_end = current_period['end']
                        new_start = new_end - max_duration_seconds
                    current_period['start'] = new_start
                    current_period['end'] = new_end
                if current_period.get('comments'):
                    sorted_comments = sorted(
                        current_period['comments'],
                        key=lambda x: x.get('positive_score', 0),
                        reverse=True
                    )
                    current_period['sample_comments'] = sorted_comments[:5]
                else:
                    current_period['sample_comments'] = []
                if 'actual_excitement_start' in current_period:
                    del current_period['actual_excitement_start']
                merged_periods.append(current_period)
            current_period = period.copy()
    if current_period is not None:
        duration = current_period['end'] - current_period['start']
        if duration >= min_duration_seconds:
            if duration > max_duration_seconds:
                center = current_period.get('best_score_time', (current_period['start'] + current_period['end'])/2)
                new_start = center - max_duration_seconds / 2
                new_end = center + max_duration_seconds / 2
                if new_start < current_period['start']:
                    new_start = current_period['start']
                    new_end = new_start + max_duration_seconds
                elif new_end > current_period['end']:
                    new_end = current_period['end']
                    new_start = new_end - max_duration_seconds
                current_period['start'] = new_start
                current_period['end'] = new_end
            if current_period.get('comments'):
                sorted_comments = sorted(
                    current_period['comments'],
                    key=lambda x: x.get('positive_score', 0),
                    reverse=True
                )
                current_period['sample_comments'] = sorted_comments[:5]
            else:
                current_period['sample_comments'] = []
            if 'actual_excitement_start' in current_period:
                del current_period['actual_excitement_start']
            merged_periods.append(current_period)
    merged_periods.sort(key=lambda x: x.get('max_score', 0), reverse=True)
    for period in merged_periods:
        if 'comments' in period:
            del period['comments']
    return merged_periods

def smooth_scores(excitement_df, window_sec=7):
    if excitement_df is None or len(excitement_df) == 0:
        return excitement_df
    df = excitement_df.copy()
    for col in ['laugh_score', 'healing_score', 'chaos_score']:
        if col in df.columns:
            arr = df[col].values
            window = window_sec
            if len(arr) < window:
                smoothed = arr
            else:
                smoothed = np.convolve(arr, np.ones(window)/window, mode='same')
            df[f'smoothed_{col}'] = smoothed
    return df

def extract_top_windows(df, score_col, window_size=10, top_n=15, min_start=None, max_end=None):
    arr = df[score_col].values
    starts = [int(x) for x in df['start_time'].values]
    ends = [int(x) for x in df['end_time'].values]
    n = len(arr)
    window_scores = []
    for i in range(n - window_size + 1):
        s = int(starts[i])
        e = int(ends[i + window_size - 1])
        if (min_start is not None and s < min_start) or (max_end is not None and e > max_end):
            continue
        total = float(arr[i:i+window_size].sum())
        window_scores.append((s, e, total))
    window_scores = sorted(window_scores, key=lambda x: x[2], reverse=True)[:top_n]
    return window_scores

def analyze_excitement(comments, duration_minutes, window_size_seconds=10, intro_duration_minutes=3, ending_duration_minutes=3):
    """時間帯ごとの盛り上がりを分析（導入部分を除外可能）"""
    total_seconds = duration_minutes * 60
    time_bins = np.arange(0, total_seconds + window_size_seconds, window_size_seconds)
    comment_counts = defaultdict(int)
    positive_scores = defaultdict(int)
    laugh_scores = defaultdict(int)
    healing_scores = defaultdict(int)
    chaos_scores = defaultdict(int)
    comments_by_bin = defaultdict(list)
    for comment in comments:
        if 'timestamp' in comment and comment['timestamp'] is not None:
            seconds = comment['timestamp']
            if seconds <= total_seconds:
                bin_index = int(seconds // window_size_seconds)
                comment_counts[bin_index] += 1
                positive_scores[bin_index] += comment.get('positive_score', 0)
                laugh_scores[bin_index] += comment.get('laugh_score', 0)
                healing_scores[bin_index] += comment.get('healing_score', 0)
                chaos_scores[bin_index] += comment.get('chaos_score', 0)
                comments_by_bin[bin_index].append(comment)
    excitement_df = pd.DataFrame({
        'start_time': [i * window_size_seconds for i in range(len(time_bins)-1)],
        'end_time': [(i+1) * window_size_seconds for i in range(len(time_bins)-1)],
        'comment_count': [comment_counts.get(i, 0) for i in range(len(time_bins)-1)],
        'positive_score': [positive_scores.get(i, 0) for i in range(len(time_bins)-1)],
        'laugh_score': [laugh_scores.get(i, 0) for i in range(len(time_bins)-1)],
        'healing_score': [healing_scores.get(i, 0) for i in range(len(time_bins)-1)],
        'chaos_score': [chaos_scores.get(i, 0) for i in range(len(time_bins)-1)],
        'comments': [comments_by_bin.get(i, []) for i in range(len(time_bins)-1)]
    })
    intro_seconds = intro_duration_minutes * 60
    ending_seconds = ending_duration_minutes * 60
    total_seconds = duration_minutes * 60
    clip_mask = (excitement_df['start_time'] >= intro_seconds) & \
                (excitement_df['end_time'] <= total_seconds - ending_seconds)
    clip_data = excitement_df[clip_mask]
    if len(clip_data) > 0 and clip_data['comment_count'].max() > 0:
        clip_comment_max = clip_data['comment_count'].max()
        excitement_df['norm_comment_count'] = excitement_df['comment_count'] / clip_comment_max
    else:
        excitement_df['norm_comment_count'] = 0
    if len(clip_data) > 0 and clip_data['positive_score'].max() > 0:
        clip_positive_max = clip_data['positive_score'].max()
        excitement_df['norm_positive_score'] = excitement_df['positive_score'] / clip_positive_max
    else:
        excitement_df['norm_positive_score'] = 0
    excitement_df['excitement_score'] = excitement_df['norm_comment_count'] * 0.6 + excitement_df['norm_positive_score'] * 0.4
    return excitement_df

def detect_excitement_periods(excitement_df, threshold=0, min_duration_seconds=5, max_duration_seconds=60, lead_in_seconds=15, min_start_time=0, max_end_time=None, trail_out_seconds=5):
    """スコアの高い上位50件の盛り上がり期間を検出（最小開始時間を指定可能）"""
    excitement_periods = []
    filtered_df = excitement_df[
        (excitement_df['start_time'] >= min_start_time) & 
        ((max_end_time is None) | (excitement_df['end_time'] <= max_end_time))
    ]
    top_10_rows = filtered_df.nlargest(40, 'excitement_score')
    for idx, row in top_10_rows.iterrows():
        if row['excitement_score'] > threshold:
            start_time = max(min_start_time, row['start_time'] - lead_in_seconds)
            end_time = row['end_time'] + trail_out_seconds
            if start_time >= end_time:
                continue
            if max_end_time and end_time > max_end_time:
                end_time = max_end_time
                if start_time >= end_time:
                    continue
            period = {
                'start': start_time,
                'end': end_time,
                'max_score': row['excitement_score'],
                'best_score_time': row['start_time'],
                'comments': row['comments'].copy() if row['comments'] else [],
                'actual_excitement_start': row['start_time'],
                'original_start': row['start_time'],
                'original_end': row['end_time']
            }
            excitement_periods.append(period)
    merged_periods = []
    if excitement_periods:
        periods_for_merge = excitement_periods.copy()
        periods_for_merge.sort(key=lambda x: x['start'])
        current_period = None
        for period in periods_for_merge:
            if current_period is None:
                current_period = period.copy()
            elif period['start'] <= current_period['end'] + 10:
                current_period['end'] = max(current_period['end'], period['end'])
                if period['max_score'] > current_period['max_score']:
                    current_period['max_score'] = period['max_score']
                    current_period['best_score_time'] = period['best_score_time']
                current_period['comments'].extend(period['comments'])
            else:
                duration = current_period['end'] - current_period['start']
                if duration >= min_duration_seconds:
                    if duration > max_duration_seconds:
                        center = current_period['best_score_time']
                        new_start = center - max_duration_seconds / 2
                        new_end = center + max_duration_seconds / 2
                        if new_start < current_period['start']:
                            new_start = current_period['start']
                            new_end = new_start + max_duration_seconds
                        elif new_end > current_period['end']:
                            new_end = current_period['end']
                            new_start = new_end - max_duration_seconds
                        current_period['start'] = new_start
                        current_period['end'] = new_end
                    if current_period['comments']:
                        sorted_comments = sorted(
                            current_period['comments'], 
                            key=lambda x: x.get('positive_score', 0), 
                            reverse=True
                        )
                        current_period['sample_comments'] = sorted_comments[:5]
                    else:
                        current_period['sample_comments'] = []
                    if 'actual_excitement_start' in current_period:
                        del current_period['actual_excitement_start']
                    merged_periods.append(current_period)
                current_period = period.copy()
        if current_period is not None:
            duration = current_period['end'] - current_period['start']
            if duration >= min_duration_seconds:
                if duration > max_duration_seconds:
                    center = current_period['best_score_time']
                    new_start = center - max_duration_seconds / 2
                    new_end = center + max_duration_seconds / 2
                    if new_start < current_period['start']:
                        new_start = current_period['start']
                        new_end = new_start + max_duration_seconds
                    elif new_end > current_period['end']:
                        new_end = current_period['end']
                        new_start = new_end - max_duration_seconds
                    current_period['start'] = new_start
                    current_period['end'] = new_end
                if current_period['comments']:
                    sorted_comments = sorted(
                        current_period['comments'], 
                        key=lambda x: x.get('positive_score', 0), 
                        reverse=True
                    )
                    current_period['sample_comments'] = sorted_comments[:5]
                else:
                    current_period['sample_comments'] = []
                if 'actual_excitement_start' in current_period:
                    del current_period['actual_excitement_start']
                merged_periods.append(current_period)
    merged_periods.sort(key=lambda x: x['max_score'], reverse=True)
    for period in merged_periods:
        if 'comments' in period:
            del period['comments']
    merged_periods.sort(key=lambda x: x['max_score'], reverse=True)
    return merged_periods[:10]

def generate_clip_urls(video_url, excitement_periods):
    """盛り上がり期間に対応するYouTubeクリップURLを生成（順位付き）"""
    clip_urls = []
    video_id = None
    if "youtube.com/watch?v=" in video_url:
        video_id = video_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in video_url:
        video_id = video_url.split("youtu.be/")[1].split("?")[0]
    for i, period in enumerate(excitement_periods):
        rank = i + 1
        start_seconds = int(period['start'])
        end_seconds = int(period['end'])
        start_formatted = str(timedelta(seconds=start_seconds))
        end_formatted = str(timedelta(seconds=end_seconds))
        clip_url = f"https://www.youtube.com/watch?v={video_id}&t={start_seconds}s"
        duration = end_seconds - start_seconds
        score_percent = int(period['max_score'] * 100)
        clip_info = {
            'url': clip_url,
            'start_time': start_formatted,
            'end_time': end_formatted,
            'start_sec': start_seconds,
            'end_sec': end_seconds,
            'duration': duration,
            'max_score': period['max_score'],
            'score_percent': score_percent,
            'rank': rank,
            'sample_comments': period.get('sample_comments', [])
        }
        clip_urls.append(clip_info)
    return clip_urls
