from PIL import Image

def plot_comment_count_graph(graph_width:int, graph_height:int, excitement_df, output_path, duration_minutes=30, num_bins=120, with_label=True):
    """コメント数のみのグラフを緑色で出力（ピークは濃い緑）"""
    setup_japanese_font()
    fig, ax = plt.subplots(figsize=(graph_width/100, graph_height/100), dpi=100)
    # ビン集約
    if num_bins is not None and num_bins > 0:
        total_minutes = duration_minutes
        bin_edges = np.linspace(0, total_minutes, num_bins + 1)
        excitement_df = excitement_df.copy()
        excitement_df['minute'] = excitement_df['start_time'] / 60
        binned = []
        for i in range(num_bins):
            bin_start = bin_edges[i]
            bin_end = bin_edges[i+1]
            bin_df = excitement_df[(excitement_df['minute'] >= bin_start) & (excitement_df['minute'] < bin_end)]
            if not bin_df.empty:
                max_count = bin_df['comment_count'].max()
            else:
                max_count = 0
            binned.append({'minute': (bin_start + bin_end) / 2, 'comment_count': max_count})
        plot_df = pd.DataFrame(binned)
        times = plot_df['minute']
        counts = plot_df['comment_count']
    else:
        times = excitement_df['start_time'] / 60
        counts = excitement_df['comment_count']
    peak_idx = counts.idxmax()
    bar_colors = ['#006400' if i == peak_idx else "#1FB81F" for i in counts.index]
    ax.bar(times, counts, width=(times.iloc[1]-times.iloc[0] if len(times)>1 else 1), alpha=0.7, color=bar_colors)
    min_count = counts.min()
    max_count = counts.max()
    # Y軸最大値を最大値の1.25倍（最大値がグラフの80%位置になるように）
    ax.set_ylim(min_count * 0.9, max_count * 1.25)
    ax.set_xlim(0, duration_minutes)
    # ラベル・軸・数値非表示
    # スコアtop1のみ星マーク＋ラベルを表示
    top1_idx = counts.idxmax()
    x = times.iloc[top1_idx] if hasattr(times, 'iloc') else times[top1_idx]
    y = counts.iloc[top1_idx] if hasattr(counts, 'iloc') else counts[top1_idx]
    label_h = max_count * 1.25/20
    ax.scatter(x, y, s=800, marker='*', color='#FFD700', edgecolors='black', linewidths=3, zorder=5)
    label_y = y 
    import matplotlib.patheffects as path_effects
    x_ratio=x/(duration_minutes if duration_minutes > 0 else 1)
    if x_ratio<0.5:
        ha= 'left'
        x = x + 2*duration_minutes/120  # 少し右にずらす
    else:
        ha= 'right'
        x = x - 2*duration_minutes/120  # 少し左にずらす
    txt = ax.text(x, label_y, f'{int(y)}', fontsize=60, color='#006400', fontweight='bold', va='center', ha=ha, zorder=6)
    txt.set_path_effects([path_effects.Stroke(linewidth=4, foreground='black'), path_effects.Normal()])
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("")
    ax.grid(False)
    plt.tight_layout(pad=0)
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    plt.savefig(output_path, dpi=100, bbox_inches=None, facecolor='white')
    plt.close()
    # --- クロマキーで白を抜いて透過画像生成 ---
    img = Image.open(output_path).convert('RGBA')
    datas = img.getdata()
    newData = []
    for item in datas:
        if item[0] == 255 and item[1] == 255 and item[2] == 255:
            newData.append((255, 255, 255, 0))
        else:
            newData.append(item)
    img.putdata(newData)
    img.save(output_path)
    if with_label:
        # --- 指定画像をレイヤー1、グラフをレイヤー2としてオーバーレイ合成 ---
        overlay_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'graph_overlay', 'comment.PNG')
        if os.path.exists(overlay_path):
            overlay = Image.open(overlay_path).convert('RGBA').resize(img.size)
            # レイヤー1: overlay, レイヤー2: img（グラフ）
            result = overlay.copy()
            result = Image.alpha_composite(result, img)
            result.save(output_path)
    return output_path

def plot_score_graph(graph_width:int, graph_height:int, excitement_df, score_col, output_path, video_title='', intro_duration_minutes=3, ending_duration_minutes=3, duration_minutes=30, num_bins=120, with_label=True):
    """任意のスコア列のグラフを生成（コメント数＋スコア）"""
    setup_japanese_font()
    fig, ax1 = plt.subplots(figsize=(graph_width/100, graph_height/100), dpi=100)
    ax2 = ax1.twinx()
    # ビン集約処理
    if num_bins is not None and num_bins > 0:
        total_minutes = duration_minutes
        bin_edges = np.linspace(0, total_minutes, num_bins + 1)
        excitement_df = excitement_df.copy()
        excitement_df['minute'] = excitement_df['start_time'] / 60
        # 各ビンごとにmax集約
        binned = []
        for i in range(num_bins):
            bin_start = bin_edges[i]
            bin_end = bin_edges[i+1]
            bin_df = excitement_df[(excitement_df['minute'] >= bin_start) & (excitement_df['minute'] < bin_end)]
            if not bin_df.empty:
                max_row = bin_df.loc[bin_df[score_col].idxmax()]
                binned.append({
                    'minute': (bin_start + bin_end) / 2,
                    'comment_count': bin_df['comment_count'].max(),
                    score_col: max_row[score_col]
                })
            else:
                binned.append({
                    'minute': (bin_start + bin_end) / 2,
                    'comment_count': 0,
                    score_col: 0
                })
        plot_df = pd.DataFrame(binned)
        times = plot_df['minute']
        comment_counts = plot_df['comment_count']
        scores = plot_df[score_col]
    else:
        times = excitement_df['start_time'] / 60
        comment_counts = excitement_df['comment_count']
        scores = excitement_df[score_col]
    # コメント数の棒グラフは描画しない
    # スコアtop1のみ星マーク＋ラベルを表示
    min_score = scores.min()
    max_score = scores.max()
    label_h = max_score * 1.25/20
    ax2.set_ylim(min_score * 0.9, max_score * 1.25)
    ax1.set_xlim(0, duration_minutes)
    top1_idx = scores.idxmax()
    x = times.iloc[top1_idx] if hasattr(times, 'iloc') else times[top1_idx]
    y = scores.iloc[top1_idx] if hasattr(scores, 'iloc') else scores[top1_idx]
    ax2.scatter(x, y, s=800, marker='*', color='#FFD700', edgecolors='black', linewidths=3, zorder=5)
    label_y = y
    # label_y = y + label_h*2
    # 色指定
    color_map = {
        'laugh_score': ('#FFAA00', '#FF4500'),
        'smoothed_laugh_score': ('#FFAA00', '#FF4500'),
        'healing_score': ('#00FFFF', '#00B0FF'),
        'smoothed_healing_score': ('#00FFFF', '#00B0FF') ,
        'chaos_score': ('#FF80FF', '#FF00AA'),
        'smoothed_chaos_score': ('#FF80FF', '#FF00AA')
    }
    base_color, peak_color = color_map.get(score_col, ('#FF0000', "#B00000"))
    import matplotlib.patheffects as path_effects
    x_ratio=x/(duration_minutes if duration_minutes > 0 else 1)
    if x_ratio<0.5:
        ha= 'left'
        x = x + 2*duration_minutes/120  # 少し右にずらす
    else:
        ha= 'right'
        x = x - 2*duration_minutes/120  # 少し左にずらす
    txt = ax2.text(x, label_y, f'{int(y)}', fontsize=60, color=base_color, fontweight='bold', va='center', ha=ha, zorder=6)
    txt.set_path_effects([path_effects.Stroke(linewidth=4, foreground=peak_color), path_effects.Normal()])
    peak_idx = scores.idxmax()
    bar_colors = [peak_color if i == peak_idx else base_color for i in scores.index]
    ax2.bar(times, scores, width=(times.iloc[1]-times.iloc[0] if len(times)>1 else 1), alpha=0.5, color=bar_colors)
    # 軸・数値・タイトル・ラベル削除
    ax1.set_xticks([])
    ax1.set_yticks([])
    ax2.set_xticks([])
    ax2.set_yticks([])
    ax1.set_xlabel("")
    ax1.set_ylabel("")
    ax2.set_ylabel("")
    ax1.set_title("")
    ax1.grid(False)
    plt.tight_layout(pad=0)
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    plt.savefig(output_path, dpi=100, bbox_inches=None, facecolor='white')
    plt.close()
    # --- クロマキーで白を抜いて透過画像生成 ---
    img = Image.open(output_path).convert('RGBA')
    datas = img.getdata()
    newData = []
    for item in datas:
        if item[0] == 255 and item[1] == 255 and item[2] == 255:
            newData.append((255, 255, 255, 0))
        else:
            newData.append(item)
    img.putdata(newData)
    img.save(output_path)
    if with_label:
        # --- 指定画像をレイヤー1、グラフをレイヤー2としてオーバーレイ合成 ---
        overlay_map = {
            'laugh_score': 'laugh.PNG',
            'smoothed_laugh_score': 'laugh.PNG',
            'healing_score': 'healing.PNG',
            'smoothed_healing_score': 'healing.PNG',
            'chaos_score': 'chaos.PNG',
            'smoothed_chaos_score': 'chaos.PNG'
        }
        overlay_file = overlay_map.get(score_col, None)
        if overlay_file:
            overlay_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'graph_overlay', overlay_file)
            if os.path.exists(overlay_path):
                overlay = Image.open(overlay_path).convert('RGBA').resize(img.size)
                result = overlay.copy()
                result = Image.alpha_composite(result, img)
                result.save(output_path)
    return output_path

def plot_multi_score_graph(excitement_df, output_path, video_title='', intro_duration_minutes=3, ending_duration_minutes=3, duration_minutes=30, num_bins=120):
    """3つのスコアを重ねたグラフを生成"""
    setup_japanese_font()
    fig, ax1 = plt.subplots(figsize=(1280/100, 720/100), dpi=100)
    # ビン集約処理
    if num_bins is not None and num_bins > 0:
        total_minutes = duration_minutes
        bin_edges = np.linspace(0, total_minutes, num_bins + 1)
        excitement_df = excitement_df.copy()
        excitement_df['minute'] = excitement_df['start_time'] / 60
        binned = []
        for i in range(num_bins):
            bin_start = bin_edges[i]
            bin_end = bin_edges[i+1]
            bin_df = excitement_df[(excitement_df['minute'] >= bin_start) & (excitement_df['minute'] < bin_end)]
            if not bin_df.empty:
                max_row = bin_df.loc[bin_df[['laugh_score','healing_score','chaos_score']].max(axis=1).idxmax()]
                binned.append({
                    'minute': (bin_start + bin_end) / 2,
                    'comment_count': bin_df['comment_count'].max(),
                    'laugh_score': bin_df['laugh_score'].max(),
                    'healing_score': bin_df['healing_score'].max(),
                    'chaos_score': bin_df['chaos_score'].max()
                })
            else:
                binned.append({
                    'minute': (bin_start + bin_end) / 2,
                    'comment_count': 0,
                    'laugh_score': 0,
                    'healing_score': 0,
                    'chaos_score': 0
                })
        plot_df = pd.DataFrame(binned)
        times = plot_df['minute']
        comment_counts = plot_df['comment_count']
        laugh_scores = plot_df['laugh_score']
        healing_scores = plot_df['healing_score']
        chaos_scores = plot_df['chaos_score']
    else:
        times = excitement_df['start_time'] / 60
        comment_counts = excitement_df['comment_count']
        laugh_scores = excitement_df['laugh_score']
        healing_scores = excitement_df['healing_score']
        chaos_scores = excitement_df['chaos_score']
    # ラベル
    ax1.text(20, 60, '3スコア', fontsize=48, color='#222', fontweight='bold', va='top', ha='left')
def label_for_score_col(score_col):
    if 'laugh' in score_col:
        return '爆笑指数'
    if 'healing' in score_col:
        return 'かわいさ指数'
    if 'chaos' in score_col:
        return '盛り上がり指数'
    if 'comment' in score_col:
        return 'コメント数'
    return score_col

def combine_graphs_to_canvas(graph_paths, output_path):
    """1280x720キャンバスに4分割でグラフ画像を合成（左上は空白）"""
    from PIL import Image
    canvas = Image.new('RGB', (1280, 720), (255, 255, 255))
    def paste_pair(img1_path, img2_path, out_path):
        canvas = Image.new('RGB', (1280, 720), (255, 255, 255))
        img1 = Image.open(img1_path).resize((640, 360))
        img2 = Image.open(img2_path).resize((640, 360))
        canvas.paste(img1, (0, 0))      # 左上
        canvas.paste(img2, (640, 360)) # 右下
        # 白色クロマキー透過
        canvas = canvas.convert('RGBA')
        datas = canvas.getdata()
        newData = []
        for item in datas:
            if item[0] == 255 and item[1] == 255 and item[2] == 255:
                newData.append((255, 255, 255, 0))
            else:
                newData.append((item[0], item[1], item[2], 255))
        canvas.putdata(newData)
        canvas.save(out_path)
        return out_path

    # 3パターンの組み合わせで出力
    if len(graph_paths) >= 3:
        # 1. 左上:爆笑, 右下:かわいさ
        paste_pair(graph_paths[0], graph_paths[1], output_path.replace('.png', '_laugh_healing.png'))
        # 2. 左上:かわいさ, 右下:盛り上がり
        paste_pair(graph_paths[1], graph_paths[2], output_path.replace('.png', '_healing_chaos.png'))
        # 3. 左上:盛り上がり, 右下:爆笑
        paste_pair(graph_paths[2], graph_paths[0], output_path.replace('.png', '_chaos_laugh.png'))
    return output_path
"""
可視化・グラフ描画系ユーティリティ
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os

def plot_twitter_graphs(excitement_df, output_dir, duration_minutes=30, num_bins=240):
    """
    Twitter用に各スコア・コメント数を240ビンでグラフ化し、軸ラベル・値をしっかり描画する。
    output_dir: 保存先ディレクトリ
    excitement_df: 必要な列（start_time, comment_count, laugh_score, healing_score, chaos_score）を含むDataFrame
    duration_minutes: 動画の長さ（分）
    num_bins: ビン数（デフォルト240）
    """

    import matplotlib.ticker as ticker
    os.makedirs(output_dir, exist_ok=True)
    graph_w, graph_h = 1280, 720
    bin_edges = np.linspace(0, duration_minutes, num_bins + 1)
    excitement_df = excitement_df.copy()
    excitement_df['minute'] = excitement_df['start_time'] / 60
    def bin_max(df, col):
        binned = []
        for i in range(num_bins):
            bin_start = bin_edges[i]
            bin_end = bin_edges[i+1]
            bin_df = df[(df['minute'] >= bin_start) & (df['minute'] < bin_end)]
            if not bin_df.empty:
                max_val = bin_df[col].max()
            else:
                max_val = 0
            binned.append({'minute': (bin_start + bin_end) / 2, col: max_val})
        plot_df = pd.DataFrame(binned)
        return plot_df['minute'], plot_df[col]

    graph_specs = [
        ('comment_count', 'コメント数', '#1FB81F'),
        ('laugh_score', '爆笑指数', '#FFAA00'),
        ('healing_score', 'かわいさ指数', '#00B0FF'),
        ('chaos_score', '盛り上がり指数', '#FF00AA'),
    ]
    output_paths = {}
    for col, ylabel, color in graph_specs:
        times, values = bin_max(excitement_df, col)
        fig, ax = plt.subplots(figsize=(graph_w/100, graph_h/100), dpi=100)
        ax.bar(times, values, width=(times.iloc[1]-times.iloc[0] if len(times)>1 else 1), alpha=0.7, color=color)
        ax.set_xlim(0, duration_minutes)
        ax.set_xlabel('時間', fontsize=24)
        ax.set_ylabel(ylabel, fontsize=24)
        # X軸ラベルを8個程度に間引き、hh:mm形式で表示
        num_labels = 8
        label_positions = np.linspace(0, duration_minutes, num_labels)
        def min_to_hhmm(minute):
            total_seconds = int(minute * 60)
            hh = total_seconds // 3600
            mm = (total_seconds % 3600) // 60
            return f"{hh:02d}:{mm:02d}"
        ax.set_xticks(label_positions)
        ax.set_xticklabels([min_to_hhmm(m) for m in label_positions], fontsize=18)
        ax.tick_params(axis='y', labelsize=18)
        # Y軸: 0, max/5ごと
        max_val = values.max()
        if max_val > 0:
            step = max(1, int(max_val/5))
            ax.yaxis.set_major_locator(ticker.MultipleLocator(step))
        ax.grid(True, alpha=0.3, axis='x')
        ax.grid(True, alpha=0.3, axis='y')
        plt.tight_layout()
        out_path = os.path.join(output_dir, f'twitter_{col}.png')
        plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        output_paths[col] = out_path
    return output_paths

def setup_japanese_font():
    """日本語フォントを設定"""

    if os.name == 'nt':
        # システムに確実に存在するフォントのみを指定（Meiryoが一般的）
        plt.rcParams['font.family'] = ['Meiryo', 'sans-serif']
    else:
        # MacやLinuxではデフォルト（指定しない）
        pass

        # フォント警告を非表示にする
        import warnings
        import logging
        warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
        logging.captureWarnings(True)
        logging.getLogger("py.warnings").setLevel(logging.ERROR)

def plot_excitement_graph(excitement_df, excitement_periods, output_path='excitement_graph.png', video_title='', intro_duration_minutes=3, ending_duration_minutes=3, duration_minutes=30):
    """盛り上がり度のグラフを生成（クリップ位置タイムラインを削除）"""
    setup_japanese_font()
    fig, ax1 = plt.subplots(figsize=(15.86, 10))
    num_clips = len(excitement_periods)
    print(f'実際のクリップ数：{num_clips}個')
    ax1.axvspan(0, intro_duration_minutes, alpha=0.1, color='gray', zorder=0, label='導入部分（クリップ対象外）')
    ax1.text(intro_duration_minutes/2, ax1.get_ylim()[1] * 0.02, f'導入部分({intro_duration_minutes}分)',  ha='center', va='bottom', fontsize=10, color='gray', style='italic')
    ax1.axvspan(duration_minutes-ending_duration_minutes, duration_minutes, alpha=0.1, color='gray', zorder=0, label='エンディング部分（クリップ対象外）')
    ax1.text(duration_minutes-ending_duration_minutes/2, ax1.get_ylim()[1] * 0.02, f'エンディング部分({ending_duration_minutes}分)',  ha='center', va='bottom', fontsize=10, color='gray', style='italic')
    times = excitement_df['start_time'] / 60
    ax1_bar = ax1.bar(times, excitement_df['comment_count'], width=10/60, alpha=0.5, color='lightblue', label='コメント数')
    ax1_twin = ax1.twinx()
    ax1_line = ax1_twin.plot(times, excitement_df['excitement_score'], color='red', linewidth=2, label='盛り上がり度スコア')
    min_score = excitement_df['excitement_score'].min()
    max_score = excitement_df['excitement_score'].max()
    ax1_twin.set_ylim(min_score * 0.9, max_score * 1.1)
    colors = plt.cm.Set3(np.linspace(0, 1, max(num_clips, 1)))
    for i, period in enumerate(excitement_periods):
        start_min = period['start'] / 60
        end_min = period['end'] / 60
        period_mask = (excitement_df['start_time'] >= period['start']) & (excitement_df['start_time'] <= period['end'])
        period_data = excitement_df[period_mask]
        max_score_idx = period_data['excitement_score'].idxmax()
        actual_time = excitement_df.loc[max_score_idx, 'start_time'] / 60
        max_score = excitement_df.loc[max_score_idx, 'excitement_score']
        ax1_twin.scatter(actual_time, max_score, s=200, facecolors='none', edgecolors='black', linewidths=3, zorder=5)
        ax1_twin.scatter(actual_time, max_score, s=150, color=colors[i % len(colors)], alpha=0.8, zorder=6)
        ax1_twin.text(actual_time, max_score, f'{i+1}', ha='center', va='center', fontsize=10, fontweight='bold', color='black', zorder=7)
    ax1.set_xlabel('時間（分）', fontsize=12)
    ax1.set_ylabel('コメント数', fontsize=12, color='blue')
    ax1_twin.set_ylabel('盛り上がり度スコア', fontsize=12, color='red')
    title = f'盛り上がり分析'
    if video_title:
        title += f': {video_title[:50]}{"..." if len(video_title) > 50 else ""}'
    ax1.set_title(title, fontsize=16, fontweight='bold', pad=20)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax1_twin.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=3, frameon=True, fancybox=True, shadow=True, columnspacing=2.0)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, max(times))
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    return output_path

def create_comment_heatmap(comments, duration_minutes, output_path='comment_heatmap.png'):
    """コメントのヒートマップを生成"""
    setup_japanese_font()
    bin_seconds = 10
    total_seconds = duration_minutes * 60
    bins = np.arange(0, total_seconds + bin_seconds, bin_seconds)
    timestamps = [c['timestamp'] for c in comments if c['timestamp'] <= total_seconds]
    counts, bin_edges = np.histogram(timestamps, bins=bins)
    fig, ax = plt.subplots(figsize=(16, 4))
    times = bin_edges[:-1] / 60
    norm = plt.Normalize(vmin=0, vmax=max(counts) if max(counts) > 0 else 1)
    colors = plt.cm.YlOrRd(norm(counts))
    bars = ax.bar(times, np.ones_like(counts), width=bin_seconds/60, color=colors, edgecolor='none')
    sm = plt.cm.ScalarMappable(cmap=plt.cm.YlOrRd, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, label='コメント数')
    ax.set_xlabel('時間（分）', fontsize=12)
    ax.set_ylabel('')
    ax.set_title('コメント密度ヒートマップ', fontsize=16, fontweight='bold')
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlim(0, duration_minutes)
    ax.grid(True, alpha=0.3, axis='x')
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    return output_path

def concat_graphs_horizontal(graph_paths, output_path, target_height=720):
    """
    4つのグラフ画像を横一列に結合し、指定した高さにリサイズして保存。
    graph_paths: [コメント数, 爆笑, 可愛さ, 盛り上がり] の順
    output_path: 保存先パス
    target_height: 出力画像の高さ（下スペースの高さに合わせる）
    """
    images = [Image.open(p) for p in graph_paths]
    # すべて同じ高さにリサイズ
    resized = []
    for img in images:
        w, h = img.size
        if h != target_height:
            new_w = int(w * (target_height / h))
            img = img.resize((new_w, target_height), Image.LANCZOS)
        resized.append(img)
    total_width = sum(img.size[0] for img in resized)
    concat_img = Image.new('RGB', (total_width, target_height), (255, 255, 255))
    x = 0
    for img in resized:
        concat_img.paste(img, (x, 0))
        x += img.size[0]
    concat_img.save(output_path)
    return output_path

def create_vertical_score_graphs(
    comment_graph_path,
    laugh_graph_path,
    healing_graph_path,
    chaos_graph_path,
    output_dir
):
    """
    16:9のキャンバスに、上下2枚のスコアグラフを縦に並べて合成する。
    - 上:コメント数、下:爆笑
    - 上:かわいさ、下:盛り上がり
    2枚の画像をoutput_dirに保存し、パスを返す。
    """
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from PIL import Image
    import os


    # 画像パスから読み込み
    imgs = {
        'comment': Image.open(comment_graph_path).convert('RGBA'),
        'laugh': Image.open(laugh_graph_path).convert('RGBA'),
        'healing': Image.open(healing_graph_path).convert('RGBA'),
        'chaos': Image.open(chaos_graph_path).convert('RGBA'),
    }
    # 16:9キャンバス（1280x720）
    canvas_w, canvas_h = 1280, 720
    graph_h = canvas_h // 2
    graph_w = canvas_w
    # 各グラフをリサイズ
    for k in imgs:
        imgs[k] = imgs[k].resize((graph_w, graph_h), Image.LANCZOS)

    # 上下に2枚並べて合成
    # (A) コメント数(上)×爆笑(下)
    out_path1 = os.path.join(output_dir, 'vertical_comment_laugh.png')
    canvas1 = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
    canvas1.paste(imgs['comment'], (0,0))
    canvas1.paste(imgs['laugh'], (0,graph_h))
    # 背面にoverlay画像を合成
    overlay1_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'graph_overlay', 'comment_laugh.png')
    if os.path.exists(overlay1_path):
        overlay1 = Image.open(overlay1_path).convert('RGBA').resize((canvas_w, canvas_h), Image.LANCZOS)
        # overlayが背面、canvas1が前面
        result1 = Image.alpha_composite(overlay1, canvas1)
        result1.save(out_path1)
    else:
        canvas1.save(out_path1)

    # (B) かわいさ(上)×盛り上がり(下)
    out_path2 = os.path.join(output_dir, 'vertical_healing_chaos.png')
    canvas2 = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
    canvas2.paste(imgs['healing'], (0,0))
    canvas2.paste(imgs['chaos'], (0,graph_h))
    # 背面にoverlay画像を合成
    overlay2_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'graph_overlay', 'healing_chaos.png')
    if os.path.exists(overlay2_path):
        overlay2 = Image.open(overlay2_path).convert('RGBA').resize((canvas_w, canvas_h), Image.LANCZOS)
        result2 = Image.alpha_composite(overlay2, canvas2)
        result2.save(out_path2)
    else:
        canvas2.save(out_path2)

    output_path=create_vertical_graphs_4split(out_path1, out_path2, os.path.join(output_dir, 'vertical_combined.png'))

    return output_path

def create_vertical_graphs_4split(
    left_top_path,
    right_bottom_path,
    output_path,
    canvas_size=(1280, 720)
):
    """
    1280x720キャンバスに、
    - 左上: left_top_path（例: vertical_comment_laugh.png）
    - 右下: right_bottom_path（例: vertical_healing_chaos.png）
    をそれぞれ640x360で配置し、他は透明で合成する。
    """
    from PIL import Image
    canvas = Image.new('RGBA', canvas_size, (0,0,0,0))
    # 画像をリサイズ
    lt_img = Image.open(left_top_path).convert('RGBA').resize((canvas_size[0]//2, canvas_size[1]//2), Image.LANCZOS)
    rb_img = Image.open(right_bottom_path).convert('RGBA').resize((canvas_size[0]//2, canvas_size[1]//2), Image.LANCZOS)
    # 左上
    canvas.paste(lt_img, (0,0), lt_img)
    # 右下
    canvas.paste(rb_img, (canvas_size[0]//2, canvas_size[1]//2), rb_img)
    canvas.save(output_path)
    return output_path