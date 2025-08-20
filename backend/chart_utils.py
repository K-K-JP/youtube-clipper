"""
チャート生成・可視化系ユーティリティ
"""
import os
import math
import json
from collections import defaultdict
from utility import get_video_id_from_url

def generate_chart_data_from_comments(video_url, comments, interval=10):
    """
    コメントリストからチャート用データを生成して保存
    """
    # 1. 動画ID取得
    video_id = get_video_id_from_url(video_url)
    # 2. ディレクトリ・パス設定
    chart_dir = os.path.join('backend', 'clips', 'chart_data')
    os.makedirs(chart_dir, exist_ok=True)
    output_path = os.path.join(chart_dir, f"{video_id}_chart.json")
    # 3. 集計
    count_bins = defaultdict(int)
    laugh_bins = defaultdict(float)
    healing_bins = defaultdict(float)
    chaos_bins = defaultdict(float)
    max_time = 0
    for comment in comments:
        t = comment.get("timestamp", 0)
        if t < 0:
            continue  # 本編外は除く
        bin_index = math.floor(t / interval)
        count_bins[bin_index] += 1
        laugh_bins[bin_index] += float(comment.get("laugh_score", 0.0))
        healing_bins[bin_index] += float(comment.get("healing_score", 0.0))
        chaos_bins[bin_index] += float(comment.get("chaos_score", 0.0))
        max_time = max(max_time, t)
    chart_data = [
        {
            "time": i * interval,
            "count": count_bins[i],
            "laughScore": laugh_bins[i],
            "healingScore": healing_bins[i],
            "chaosScore": chaos_bins[i]
        }
        for i in range(0, math.ceil(max_time / interval) + 1)
    ]
    # 4. 保存
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(chart_data, f, ensure_ascii=False, indent=2)
    print(f"チャート用データを保存: {output_path}")
    return output_path