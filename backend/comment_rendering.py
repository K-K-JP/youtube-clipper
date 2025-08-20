from utility import sanitize_filename
import os
import re
import json
import time
import copy
import shutil
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import os
import time
import copy
import random
import logging
import json
import re
import hashlib
import shutil
import subprocess
import requests
from multiprocessing import Pool, cpu_count
from io import BytesIO
import requests
import logging
from PIL import Image, ImageDraw, ImageFont

# =============================
# 9:16（ショート動画）専用: 1フレーム画像保存・バッチ生成 雛形
# =============================

def render_frame_to_file_9x16(
    frame_number: int,
    frame_time: float,
    comments: list[dict],
    video_width: int,
    video_height: int,
    emoji_cache: dict,
    channel_name: str,
    emoji_processor,
    output_path: str,
    emoji_scale: float = 1.5,
    **kwargs
) -> bool:
    """
    9:16用: 1フレームをファイルに保存
    Args:
        frame_number: フレーム番号
        frame_time: フレーム時刻
        comments: コメントリスト
        video_width: 動画幅
        video_height: 動画高さ
        emoji_cache: 絵文字キャッシュ
        channel_name: チャンネル名
        emoji_processor: EmojiProcessorインスタンス
        output_path: 出力ファイルパス
        **kwargs: その他のオプション
    Returns:
        bool: 成功時True
    """
    try:
        overlay = create_comment_overlay_image_9x16(
            frame_time, comments, video_width, video_height,
            emoji_cache, channel_name, emoji_processor, emoji_scale=emoji_scale, **kwargs
        )
        overlay.save(output_path, "PNG")
        return True
    except Exception as e:
        # print(f"[9x16] フレーム{frame_number}の描画エラー: {e}")
        return False


class VideoProcessor9x16:
    """9:16ショート動画専用: フレームバッチ生成クラス（雛形）"""
    def __init__(self, temp_dir: str = "temp_frames_9x16"):
        self.temp_dir = temp_dir

    def generate_frame_images_9x16(self, comments: list[dict], emoji_cache: dict, frame_count: int, fps: int, **kwargs) -> bool:
        """
        9:16用: フレーム画像を並列生成（雛形）
        Args:
            comments: 処理済みコメントリスト
            emoji_cache: 絵文字キャッシュ
            frame_count: 総フレーム数
            fps: フレームレート
            **kwargs: その他パラメータ
        Returns:
            処理成功/失敗
        """
        import os, time
        from multiprocessing import Pool, cpu_count
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            batch_size = 100
            cpu_cores = min(cpu_count(), 8)
            batches = [(i, min(i + batch_size, frame_count)) for i in range(0, frame_count, batch_size)]
            process_args = []
            for batch_start, batch_end in batches:
                args = (batch_start, batch_end, comments, emoji_cache, fps, self.temp_dir, kwargs)
                process_args.append(args)
            start_time = time.time()
            with Pool(processes=cpu_cores) as pool:
                results = pool.map(VideoProcessor9x16._process_frame_batch_9x16, process_args)
            print(f"[9x16] フレーム生成完了: {time.time() - start_time:.2f}秒")
            return all(results)
        except Exception as e:
            print(f"[9x16] フレーム生成エラー: {e}")
            return False

    @staticmethod
    def _process_frame_batch_9x16(args: tuple) -> bool:
        batch_start, batch_end, comments, emoji_cache, fps, temp_dir, kwargs = args
        try:
            exclude_keys = {'video_width', 'video_height', 'channel_name', 'emoji_processor', 'output_path', 'frame_num', 'frame_time', 'comments', 'emoji_cache', 'emoji_scale'}
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in exclude_keys}
            emoji_scale = kwargs.get('emoji_scale', 1.5)
            for frame_num in range(batch_start, batch_end):
                frame_time = frame_num / fps
                output_path = os.path.join(temp_dir, f"{frame_num:06d}.png")
                ok = render_frame_to_file_9x16(
                    frame_number=frame_num,
                    frame_time=frame_time,
                    comments=comments,
                    video_width=kwargs.get('video_width', 1080),
                    video_height=kwargs.get('video_height', 1920),
                    emoji_cache=emoji_cache,
                    channel_name=kwargs.get('channel_name', ''),
                    emoji_processor=kwargs.get('emoji_processor', None),
                    output_path=output_path,
                    emoji_scale=emoji_scale,
                    **filtered_kwargs
                )
                if not ok:
                    print(f"[9x16] フレーム{frame_num}生成失敗")
            return True
        except Exception as e:
            print(f"[9x16] バッチ処理エラー ({batch_start}-{batch_end}): {e}")
            return False
# 9:16用: コメント位置計算関数（上下エリア分割/NicoNico-style流し）
def calculate_comment_positions_9x16(
    comments: list[dict],
    frame_time: float,
    video_width: int = 1080,
    video_height: int = 1920,
    display_duration: float = 4.0,
    top_lanes: int = 6,
    bottom_lanes: int = 6,
    top_area_ratio: float = 0.18,
    bottom_area_ratio: float = 0.18
) -> list[dict]:
    """
    9:16用: 上下エリアごとにNicoNico-styleで流すコメントの位置を計算
    Args:
        comments: レーン割り当て済みコメントリスト（'area'キー: 'top'/'bottom'）
        frame_time: 対象フレーム時刻
        video_width: 動画幅（9:16想定）
        video_height: 動画高さ
        display_duration: コメント表示時間
        top_lanes: 上エリアのレーン数
        bottom_lanes: 下エリアのレーン数
        top_area_ratio: 上エリアの高さ比率（例: 0.18=18%）
        bottom_area_ratio: 下エリアの高さ比率
    Returns:
        list[dict]: 位置情報付きアクティブコメントリスト
    """
    # Noneや空リスト対応
    comments = comments or []
    # エリアごとのY範囲を計算
    top_area_height = int(video_height * top_area_ratio)
    bottom_area_height = int(video_height * bottom_area_ratio)
    top_area_y0 = 0
    top_area_y1 = top_area_height
    bottom_area_y0 = video_height - bottom_area_height
    bottom_area_y1 = video_height

    # アクティブなコメントのみ抽出
    active_comments = []
    for comment in comments:
        start_time = comment['timestamp']
        end_time = start_time + display_duration
        if start_time <= frame_time <= end_time:
            active_comments.append(comment)

    positioned_comments = []
    for comment in active_comments:
        area = comment.get('area', 'top')
        lane = comment.get('lane', 0)
        # 進行度
        progress = (frame_time - comment['timestamp']) / display_duration
        progress = max(0.0, min(1.0, progress))
        # X座標（右→左）
        comment_width = comment.get('total_width', 200)
        start_x = video_width
        end_x = -comment_width  # 右端が画面左端に到達した時点で消える
        x = int(start_x + (end_x - start_x) * progress)
        # 右端が画面左端に到達するまで表示し続ける（完全に消えるまで）
        # 進行度1.0でx = -comment_width
        # 進行度0.0でx = video_width
        # Y座標
        if area == 'top':
            lane_height = top_area_height / top_lanes
            y = int(top_area_y0 + lane * lane_height)
        else:
            lane_height = bottom_area_height / bottom_lanes
            y = int(bottom_area_y0 + lane * lane_height)
        # visible: 右端が画面左端を"十分に"超えるまで表示（余裕を持たせる）
        # disappear_marginを大きめにして、左端から完全に消えるまで余裕を持たせる
        disappear_margin = max(int(comment_width * 0.2), 60)  # 20%幅または60pxの大きい方
        visible = (x + comment_width > -disappear_margin) and (x < video_width + disappear_margin)
        comment_with_position = {**comment, 'x': x, 'y': y, 'progress': progress, 'visible': visible}
        positioned_comments.append(comment_with_position)
    return positioned_comments
 # =============================
 # 9:16（ショート動画）専用関数群 雛形
 # =============================

def create_comment_overlay_image_9x16(
    frame_time: float,
    comments: list[dict],
    video_width: int,
    video_height: int,
    emoji_cache: dict,
    channel_name: str,
    emoji_processor,
    display_duration: float = 4.0,
    font_path: Optional[str] = None,
    font_size: int = 36,
    lane_height: Optional[int] = None,
    top_lanes: int = 6,
    bottom_lanes: int = 6,
    top_area_ratio: float = 0.18,
    bottom_area_ratio: float = 0.18,
    emoji_scale: float = 1.5
) -> Image.Image:
    """
    9:16用: 1フレームのオーバーレイ画像生成（上下エリア独立/NicoNico-style流し）
    Args:
        frame_time: フレーム時刻
        comments: レーン割り当て済みコメントリスト（'area'キー: 'top'/'bottom'）
        video_width: 動画幅（9:16想定）
        video_height: 動画高さ
        emoji_cache: 絵文字キャッシュ
        channel_name: チャンネル名
        emoji_processor: EmojiProcessorインスタンス
        display_duration: コメント表示時間
        font_path: フォントファイルパス
        font_size: フォントサイズ
        lane_height: レーン高さ
        top_lanes: 上エリアのレーン数
        bottom_lanes: 下エリアのレーン数
        top_area_ratio: 上エリアの高さ比率
        bottom_area_ratio: 下エリアの高さ比率
    Returns:
        Image.Image: RGBA形式のオーバーレイ画像
    """
    # Noneや空リスト対応
    comments = comments or []
    # 位置計算
    positioned_comments = calculate_comment_positions_9x16(
        comments, frame_time, video_width, video_height, display_duration,
        top_lanes, bottom_lanes, top_area_ratio, bottom_area_ratio
    )
    # レンダラー生成
    renderer = CommentRenderer(font_path, font_size, lane_height=lane_height, emoji_scale=emoji_scale)
    overlay = Image.new('RGBA', (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # positioned_commentsが空の場合も空画像を返す
    for comment in positioned_comments:
        if not comment.get('visible', True):
            continue
        renderer._draw_comment(
            draw, overlay, comment, emoji_cache, channel_name, emoji_processor
        )
    return overlay

def assign_comment_lanes_9x16(comments: list[dict], top_lanes: int = 6, bottom_lanes: int = 6) -> list[dict]:
    """
    9:16用: コメントを上下エリアごとに独立してレーン割り当て
    Args:
        comments: コメントリスト（各要素は 'area' キーで 'top'/'bottom' 指定必須）
        top_lanes: 上エリアの最大レーン数
        bottom_lanes: 下エリアの最大レーン数
    Returns:
        List[dict]: レーン番号が追加されたコメントリスト
    """
    import copy
    comments_with_lanes = copy.deepcopy(comments)
    # areaごとにレーン割り当て
    top_last_used = [0.0] * top_lanes
    bottom_last_used = [0.0] * bottom_lanes
    display_duration = 8.0
    # --- ここでtotal_widthを付与 ---
    # EmojiProcessorのインスタンスを仮で生成（必要に応じて外部から渡すことも可）
    emoji_processor = EmojiProcessor()
    font_size = 90  # 必要に応じて調整
    renderer = CommentRenderer(font_size=font_size)
    for comment in comments_with_lanes:
        # すでにtotal_widthがあればスキップ
        if 'total_width' not in comment:
            text = comment.get('text', '')
            comment['total_width'] = renderer.calculate_text_width(text, {}, emoji_processor)
    for comment in comments_with_lanes:
        area = comment.get('area', 'top')
        start_time = comment['timestamp']
        end_time = start_time + display_duration
        if area == 'top':
            # 最初に空いているレーンを探す
            for lane in range(top_lanes):
                if top_last_used[lane] <= start_time:
                    comment['lane'] = lane
                    top_last_used[lane] = end_time
                    break
            else:
                # 全部埋まっていたら最も早く空くレーン
                min_idx = top_last_used.index(min(top_last_used))
                comment['lane'] = min_idx
                top_last_used[min_idx] = end_time
        else:
            for lane in range(bottom_lanes):
                if bottom_last_used[lane] <= start_time:
                    comment['lane'] = lane
                    bottom_last_used[lane] = end_time
                    break
            else:
                min_idx = bottom_last_used.index(min(bottom_last_used))
                comment['lane'] = min_idx
                bottom_last_used[min_idx] = end_time
    return comments_with_lanes

# ロガー設定（必要に応じて）
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

class FrameRenderer:
    """フレーム画像生成を管理するクラス"""
    def __init__(self, video_width: int = 1920, video_height: int = 1080, 
                 font_size: int = 36, fps: int = 30, lane_height: Optional[int] = None, emoji_scale: float = 1.5):
        self.video_width = video_width
        self.video_height = video_height
        self.font_size = font_size
        self.fps = fps
        self.lane_height = lane_height if lane_height else font_size + 10  
        self.text_width_cache = {}
        self.emoji_scale = emoji_scale
        try:
            self.font = ImageFont.truetype(r"C:\\Windows\\Fonts\\meiryo.ttc", font_size)
        except:
            try:
                self.font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
            except:
                self.font = ImageFont.load_default()

    def _draw_text_element(self, draw: ImageDraw.Draw, element: dict, x: float, y: float) -> float:
        text = element['content']
        for dx in [-1, 1, 0, 0, -1, -1, 1, 1]:
            for dy in [0, 0, -1, 1, -1, 1, -1, 1]:
                draw.text((x + dx, y + dy), text, font=self.font, fill=(0, 0, 0, 255))
        draw.text((x, y), text, font=self.font, fill=(255, 255, 255, 200))
        if text in self.text_width_cache:
            text_width = self.text_width_cache[text]
        else:
            text_width = draw.textlength(text, font=self.font)
            self.text_width_cache[text] = text_width
        return x + text_width

    def create_comment_overlay_image(self, frame_time: float, active_comments: list[dict], emoji_cache: dict) -> Image.Image:
        overlay = Image.new('RGBA', (self.video_width, self.video_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for comment in active_comments:
            self._draw_comment(draw, overlay, comment, frame_time, emoji_cache)
        return overlay

    def _draw_comment(self, draw: ImageDraw.Draw, overlay: Image.Image, comment: dict, frame_time: float, emoji_cache: dict) -> None:
        x_pos = self._calculate_comment_x_position(comment, frame_time)
        y_pos = comment['lane'] * self.lane_height + 10
        if x_pos > self.video_width or x_pos + comment.get('total_width', 0) < 0:
            return
        current_x = x_pos
        # print(f"[DEBUG elements] {comment['elements']}")
        custom_emoji_count = 0
        for element in comment['elements']:
            # print(f"[DEBUG _draw_comment] element type: {element.get('type')}, content: {element.get('content', '')}, id: {element.get('id', '')}")
            if element['type'] == 'text':
                current_x = self._draw_text_element(draw, element, current_x, y_pos)
            elif element['type'] == 'custom_emoji':
                custom_emoji_count += 1
                current_x = self._draw_emoji_element(overlay, element, current_x, y_pos, emoji_cache)
        # if custom_emoji_count == 0:
        #     print(f"[WARNING] No custom_emoji element in comment: {comment}")

    def _calculate_comment_x_position(self, comment: dict, frame_time: float, display_duration: float = 8.0) -> float:
        comment_start_time = comment['timestamp']
        elapsed_time = frame_time - comment_start_time
        if elapsed_time < 0 or elapsed_time > display_duration:
            return -1000  # 画面外
        progress = elapsed_time / display_duration
        total_width = comment.get('total_width', 200)
        start_x = self.video_width
        end_x = -total_width
        return start_x - (start_x - end_x) * progress

    def _draw_emoji_element(self, overlay: Image.Image, element: dict, x: float, y: float, emoji_cache: dict) -> float:
        emoji_id = element['id']
        emoji_size = int(self.font_size * self.emoji_scale)
        # print(f"[DEBUG _draw_emoji_element] emoji_id: {emoji_id}, emoji_cache keys: {list(emoji_cache.keys())}")
        if emoji_id in emoji_cache:
            if 'original' in emoji_cache[emoji_id]:
                orig = emoji_cache[emoji_id]['original']
        if emoji_id not in emoji_cache:
            return x
        elif 'original' not in emoji_cache[emoji_id]:
            return x
        emoji_data = emoji_cache[emoji_id]
        if 'resized' not in emoji_data:
            emoji_data['resized'] = {}
        try:
            if emoji_size in emoji_data['resized']:
                emoji_img = emoji_data['resized'][emoji_size]
            else:
                emoji_img = emoji_data['original'].resize((emoji_size, emoji_size), Image.Resampling.LANCZOS)
                if emoji_img.mode != 'RGBA':
                    emoji_img = emoji_img.convert('RGBA')
                r, g, b, a = emoji_img.split()
                a = a.point(lambda p: int(p * 1))
                emoji_img = Image.merge('RGBA', (r, g, b, a))
                emoji_data['resized'][emoji_size] = emoji_img
            emoji_y = int(y + (self.font_size - emoji_size) / 2)
            try:
                overlay.paste(emoji_img, (int(x), emoji_y), emoji_img)
            except Exception as e:
                pass
            return x + emoji_size
        except Exception as e:
            # print(f"[ERROR emoji resize/draw] emoji_id: {emoji_id}, error: {e}")
            return x
"""
コメント・サムネイル画像・動画合成関連のクラス・関数群
"""

from PIL import Image, ImageDraw, ImageFont
import random
import os

# サムネイル用オーバーレイ画像生成
def extract_comments_around_time(comments, target_time, max_comments):
    """
    指定時刻周辺のコメントを抽出
    
    Args:
        comments: 全コメントリスト
        target_time: 対象時刻（秒）
        max_comments: 最大抽出コメント数
    
    Returns:
        List[dict]: 抽出されたコメントリスト
    """
    # 対象時刻の前後60秒の範囲でコメントを取得
    time_window = 60.0
    start_window = max(0, target_time - time_window)
    end_window = target_time + time_window
    
    # 時間範囲内のコメントを抽出
    candidate_comments = [
        c for c in comments 
        if start_window <= c['timestamp'] <= end_window
    ]
    
    if len(candidate_comments) <= max_comments:
        # 候補が少ない場合はそのまま返す
        selected_comments = candidate_comments
    else:
        # 対象時刻に近い順にソートして上位を選択
        candidate_comments.sort(key=lambda x: abs(x['timestamp'] - target_time))
        selected_comments = candidate_comments[:max_comments]
    
    # timestamp を 0 からの相対時間に調整（既存のコメント処理と合わせる）
    for c in selected_comments:
        c['timestamp'] = c['timestamp'] - target_time + 4.0  # 4秒後に表示開始
    
    return selected_comments

def create_thumbnail_overlay_image(comments, emoji_cache, channel_name, 
                                 emoji_processor, max_lanes=20,
                                 video_width=1920, video_height=1080):
    """
    サムネイル用の静止画オーバーレイを生成
    Args:
        comments: レーン割り当て済みコメントリスト
        emoji_cache: 絵文字キャッシュ
        channel_name: チャンネル名
        emoji_processor: EmojiProcessorインスタンス
        max_lanes: レーン数
        video_width: 動画幅
        video_height: 動画高さ
    Returns:
        Image.Image: RGBA形式のオーバーレイ画像
    """
    overlay = Image.new('RGBA', (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = 55
    try:
        font = ImageFont.truetype(r"C:\\Windows\\Fonts\\meiryo.ttc", font_size)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
    lane_height = video_height / max_lanes
    used_x_positions = []
    for comment in comments:
        lane = comment.get('lane', 0)
        y_pos = int(lane * lane_height)
        for _ in range(10):
            x_pos_candidate = random.randint(-200, video_width + 100)
            if all(abs(x_pos_candidate - ux) > 150 for ux in used_x_positions):
                break
        used_x_positions.append(x_pos_candidate)
        current_x = x_pos_candidate
        for element in comment['elements']:
            if element['type'] == 'text':
                text_content = element['content']
                if text_content:
                    outline_width = 4
                    for dx in range(-outline_width, outline_width + 1):
                        for dy in range(-outline_width, outline_width + 1):
                            if dx != 0 or dy != 0:
                                draw.text((current_x + dx, y_pos + dy), text_content, font=font, fill=(0, 0, 0, 255))
                    draw.text((current_x, y_pos), text_content, font=font, fill=(255, 255, 255, 255))
                    try:
                        bbox = draw.textbbox((0, 0), text_content, font=font)
                        text_width = bbox[2] - bbox[0]
                        current_x += text_width
                    except:
                        current_x += len(text_content) * font_size // 2
            elif element['type'] == 'custom_emoji':
                emoji_id = element['id']
                if emoji_id in emoji_cache and 'original' in emoji_cache[emoji_id]:
                    emoji_img = emoji_cache[emoji_id]['original']
                    emoji_size = font_size
                    emoji_img = emoji_img.resize((emoji_size, emoji_size), Image.Resampling.LANCZOS)
                    emoji_y = int(y_pos + (font_size - emoji_size) // 2)
                    try:
                        overlay.paste(emoji_img, (current_x, emoji_y), emoji_img)
                    except Exception as e:
                        pass
                    current_x += emoji_size
    return overlay

class CommentRenderer:
    """コメント描画を管理するクラス"""
    
    def __init__(self, font_path: Optional[str] = None, font_size: int = 36, lane_height: Optional[int] = None, emoji_scale: float = 1.5):
        """
        初期化
        
        Args:
            font_path: フォントファイルパス（Noneの場合はデフォルトフォント）
            font_size: フォントサイズ
        """
        self.font_size = font_size
        self.emoji_size = (font_size, font_size)
        self.emoji_scale = emoji_scale
        
        self.frame_renderer = FrameRenderer(
            video_width=1920,
            video_height=1080,
            font_size=font_size,
            lane_height=lane_height
        )
        
        # フォントを読み込み
        try:
            if font_path and os.path.exists(font_path):
                self.font = ImageFont.truetype(font_path, font_size)
            else:
                # デフォルトフォントを試行
                try:
                    # Windows
                    self.font = ImageFont.truetype(r"C:\Windows\Fonts\meiryo.ttc", font_size)
                except:
                    try:
                        # macOS
                        self.font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
                    except:
                        try:
                            # Linux
                            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
                        except:
                            # フォールバック
                            self.font = ImageFont.load_default()
                            # print("警告: システムフォントが見つからず、デフォルトフォントを使用します")
        except Exception as e:
            # print(f"フォント読み込みエラー: {e}")
            self.font = ImageFont.load_default()
    
    def create_comment_overlay_image(self, comments_with_positions: list[dict], 
                                   video_width: int, video_height: int,
                                   emoji_cache: dict, channel_name: str,
                                   emoji_processor) -> Image.Image:
        """
        1フレームのオーバーレイ画像生成
        
        Args:
            comments_with_positions: 位置情报付きコメントリスト
            video_width: 動画幅
            video_height: 動画高さ
            emoji_cache: 絵文字キャッシュ情報
            channel_name: チャンネル名
            emoji_processor: EmojiProcessorインスタンス
        
        Returns:
            Image.Image: RGBA形式のオーバーレイ画像
        """
        # 透明背景のオーバーレイ画像を作成
        overlay = Image.new('RGBA', (video_width, video_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        for comment in comments_with_positions:
            if not comment.get('visible', True):
                continue
                
            self._draw_comment(
                draw, overlay, comment, emoji_cache, 
                channel_name, emoji_processor
            )
        
        return overlay
    
    def _draw_comment(self, draw: ImageDraw.Draw, overlay: Image.Image, 
                     comment: dict, emoji_cache: dict, channel_name: str,
                     emoji_processor) -> None:
        """
        単一コメントを描画
        
        Args:
            draw: ImageDrawオブジェクト
            overlay: オーバーレイ画像
            comment: 位置情報付きコメント
            emoji_cache: 絵文字キャッシュ
            channel_name: チャンネル名
            emoji_processor: EmojiProcessorインスタンス
        """
        x, y = comment['x'], comment['y']
        text = comment.get('text', '')
        # コメントテキストを要素に分解
        elements = emoji_processor.parse_comment_elements(text, emoji_cache)
        
        # 要素を順次描画
        current_x = x
        
        for element in elements:
            if element['type'] == 'text':
                # テキスト描画
                text_content = element['content']
                if text_content:  # 空文字列でない場合のみ描画
                    current_x = self._draw_text(draw, text_content, current_x, y)
            
            elif element['type'] == 'custom_emoji':
                # 絵文字描画
                emoji_id = element['id']
                emoji_img = emoji_processor.get_emoji_image(
                    emoji_id, emoji_cache, channel_name, self.emoji_size
                )
                
                if emoji_img:
                    current_x = self._draw_emoji(overlay, emoji_img, current_x, y)
                else:
                    # 絵文字が取得できない場合は代替テキストを描画
                    alt_text = emoji_id
                    current_x = self._draw_text(draw, alt_text, current_x, y)
            
            elif element['type'] == 'unicode_emoji':
                # Unicode絵文字描画
                emoji_char = element['content']
                emoji_img = emoji_processor.create_unicode_emoji_image(
                    emoji_char, self.font_size
                )
                
                if emoji_img:
                    current_x = self._draw_emoji(overlay, emoji_img, current_x, y)
                else:
                    # Unicode絵文字が描画できない場合は文字として描画
                    current_x = self._draw_text(draw, emoji_char, current_x, y)
    
    def _draw_text(self, draw: ImageDraw.Draw, text: str, x: int, y: int) -> int:
        """
        テキストを描画（縁取り付き）
        
        Args:
            draw: ImageDrawオブジェクト
            text: 描画するテキスト
            x: X座標
            y: Y座標
        
        Returns:
            int: 次の描画開始X座標
        """
        if not text:
            return x
        
        # テキストサイズを取得
        try:
            bbox = draw.textbbox((0, 0), text, font=self.font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except:
            # フォールバック
            text_width = len(text) * self.font_size // 2
            text_height = self.font_size
        
        # 縁取り描画（黒）
        outline_width = 2
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=self.font, fill=(0, 0, 0, 255))
        
        # メインテキスト描画（白）
        draw.text((x, y), text, font=self.font, fill=(255, 255, 255, 255))
        
        return x + text_width
    
    def _draw_emoji(self, overlay: Image.Image, emoji_img: Image.Image, 
                   x: int, y: int) -> int:
        """
        絵文字を描画
        
        Args:
            overlay: オーバーレイ画像
            emoji_img: 絵文字画像
            x: X座標
            y: Y座標
        
        Returns:
            int: 次の描画開始X座標
        """
        # 絵文字画像のサイズを取得
        emoji_width, emoji_height = emoji_img.size
        
        # Y座標をベースラインに合わせて調整
        adjusted_y = y + (self.font_size - emoji_height) // 2
        
        # 絵文字を貼り付け
        try:
            overlay.paste(emoji_img, (x, adjusted_y), emoji_img)
        except Exception as e:
            pass
        return x + emoji_width
    
    def calculate_text_width(self, text: str, emoji_cache: dict, 
                           emoji_processor) -> int:
        """
        テキストの表示幅を正確に計算
        
        Args:
            text: 計算するテキスト
            emoji_cache: 絵文字キャッシュ
            emoji_processor: EmojiProcessorインスタンス
        
        Returns:
            int: 表示幅（ピクセル）
        """
        elements = emoji_processor.parse_comment_elements(text, emoji_cache)
        total_width = 0
        
        for element in elements:
            if element['type'] == 'text':
                text_content = element['content']
                if text_content:
                    try:
                        bbox = self.font.getbbox(text_content)
                        total_width += bbox[2] - bbox[0]
                    except:
                        total_width += len(text_content) * self.font_size // 2
            
            elif element['type'] in ['emoji', 'unicode_emoji']:
                total_width += self.emoji_size[0]
        
        return total_width


def create_comment_overlay_image(frame_time: float, comments: list[dict],
                               video_width: int, video_height: int,
                               emoji_cache: dict, channel_name: str,
                               emoji_processor, display_duration: float = 8.0,
                               font_path: Optional[str] = None, 
                               font_size: int = 36, lane_height: Optional[int] = None) -> Image.Image:
    """
    1フレームのオーバーレイ画像生成（統合関数）
    
    Args:
        frame_time: フレーム時刻
        comments: レーン割り当て済みコメントリスト
        video_width: 動画幅
        video_height: 動画高さ
        emoji_cache: 絵文字キャッシュ
        channel_name: チャンネル名
        emoji_processor: EmojiProcessorインスタンス
        display_duration: コメント表示時間
        font_path: フォントファイルパス
        font_size: フォントサイズ
    
    Returns:
        Image.Image: RGBA形式のオーバーレイ画像
    """
    
    # 指定時刻でのコメント位置を計算
    positioned_comments = calculate_comment_positions(
        comments, frame_time, video_width, video_height, display_duration
    )
    
    # レンダラーを作成してオーバーレイ画像を生成
    renderer = CommentRenderer(font_path, font_size, lane_height=lane_height, emoji_scale=emoji_scale)
    overlay = renderer.create_comment_overlay_image(
        positioned_comments, video_width, video_height,
        emoji_cache, channel_name, emoji_processor
    )
    
    return overlay


def render_frame_to_file(frame_number: int, frame_time: float, 
                        comments: list[dict], video_width: int, video_height: int,
                        emoji_cache: dict, channel_name: str, emoji_processor,
                        output_path: str, **kwargs) -> bool:
    """
    1フレームをファイルに保存
    
    Args:
        frame_number: フレーム番号
        frame_time: フレーム時刻
        comments: コメントリスト
        video_width: 動画幅
        video_height: 動画高さ
        emoji_cache: 絵文字キャッシュ
        channel_name: チャンネル名
        emoji_processor: EmojiProcessorインスタンス
        output_path: 出力ファイルパス
        **kwargs: その他のオプション
    
    Returns:
        bool: 成功時True
    """
    try:
        overlay = create_comment_overlay_image(
            frame_time, comments, video_width, video_height,
            emoji_cache, channel_name, emoji_processor, **kwargs
        )
        
        # PNG形式で保存（透明背景保持）
        overlay.save(output_path, "PNG")
        return True
        
    except Exception as e:
        # print(f"フレーム{frame_number}の描画エラー: {e}")
        return False

class VideoProcessor:
    """動画処理・合成を管理するメインクラス"""
    
    def __init__(self, temp_dir: str = "temp_frames"):
        """
        Args:
            temp_dir: 一時ファイル保存ディレクトリ
        """
        self.temp_dir = temp_dir
        self.frame_renderer = FrameRenderer()
    
    def add_emoji_comments_to_video(self, video_path: str, comments: list[dict], 
                                  emoji_dict: dict, output_path: str, 
                                  fps: int = 30) -> bool:
        """
        絵文字対応コメント付き動画を生成（メイン関数）
        
        Args:
            video_path: 入力動画パス
            comments: コメントデータリスト
            emoji_dict: 絵文字辞書
            output_path: 出力動画パス
            fps: フレームレート
            
        Returns:
            処理成功/失敗
        """
        try:
            # print("=== 絵文字対応コメント動画生成開始 ===")
            
            # 1. 前処理
            # print("1. 前処理開始...")
            processed_data = self._preprocess_comments(comments, emoji_dict)
            if not processed_data:
                return False
            
            comments_with_elements, emoji_cache, video_duration = processed_data
            
            # 2. フレーム画像生成
            # print("2. フレーム画像生成開始...")
            frame_count = int(video_duration * fps)
            success = self._generate_frame_images(comments_with_elements, emoji_cache, 
                                                frame_count, fps)
            if not success:
                return False
            
            # 3. 動画合成
            # print("3. 動画合成開始...")
            success = self._combine_video_with_frames(video_path, output_path, fps)
            
            # 4. クリーンアップ
            # print("4. 一時ファイルクリーンアップ...")
            self._cleanup_temp_files()
            
            if success:
                print(f"=== 処理完了 ===")
            else:
                print("=== 処理失敗 ===")
            
            return success
            
        except Exception as e:
            print(f"エラーが発生しました: {e}")
            self._cleanup_temp_files()
            return False
    
    def _preprocess_comments(self, comments: list[dict], emoji_dict: dict) -> Optional[tuple]:
        """
        コメントの前処理を実行
        
        Args:
            comments: コメントデータリスト
            emoji_dict: 絵文字辞書
            
        Returns:
            (処理済みコメント, 絵文字キャッシュ, 動画時間) または None
        """      
        try:
            #[LOG]
            for emoji_id, info in emoji_cache.items():
                print("[絵文字キャッシュ確認]")

            # 絵文字処理
            emoji_processor = EmojiProcessor()
            emoji_cache = emoji_processor.download_and_cache_emojis(emoji_dict, "emoji_cache")
            
            # コメント要素分解
            comments_with_elements = []
            for comment in comments:
                elements = emoji_processor.parse_comment_elements(comment['text'], emoji_dict)
                comment_copy = comment.copy()
                comment_copy['elements'] = elements
                
                # 総幅を計算
                total_width = self._calculate_comment_total_width(elements, emoji_cache)
                comment_copy['total_width'] = total_width
                
                comments_with_elements.append(comment_copy)
            
            # レーン割り当て
            lane_manager = CommentLaneManager(max_lanes=10)
            comments_with_lanes = lane_manager.assign_comment_lanes(comments_with_elements)
            
            # 動画時間を計算
            video_duration = max(c['timestamp'] for c in comments) + 10.0  # 余裕を持たせる
            
            return comments_with_lanes, emoji_cache, video_duration
            
        except Exception as e:
            print(f"前処理エラー: {e}")
            return None
    
    def _calculate_comment_total_width(self, elements: list[dict], emoji_cache: dict) -> float:
        """
        コメントの総幅を正確に計算（テキストはfont.getbboxまたはdraw.textlength、絵文字は画像サイズ）
        Args:
            elements: コメント要素リスト
            emoji_cache: 絵文字キャッシュ
        Returns:
            総幅（ピクセル）
        """
        total_width = 0
        font = self.frame_renderer.font
        font_size = self.frame_renderer.font_size
        # PIL.ImageDraw.Drawが必要だが、ここではfont.getbboxで十分
        for element in elements:
            if element['type'] == 'text':
                text_content = element['content']
                if text_content:
                    try:
                        bbox = font.getbbox(text_content)
                        text_width = bbox[2] - bbox[0]
                    except Exception:
                        text_width = len(text_content) * int(font_size * 0.6)
                    total_width += text_width
            elif element['type'] == 'custom_emoji':
                emoji_id = element.get('id')
                emoji_img = None
                if emoji_id and emoji_id in emoji_cache and 'original' in emoji_cache[emoji_id]:
                    try:
                        emoji_img = Image.open(
                            Path(emoji_cache[emoji_id]['path'])
                        )
                        emoji_width = emoji_img.width
                        emoji_img.close()
                    except Exception:
                        emoji_width = font_size  # フォールバック
                else:
                    emoji_width = font_size
                total_width += emoji_width
            elif element['type'] == 'unicode_emoji':
                # Unicode絵文字はフォントサイズ正方形で仮定
                total_width += font_size
        return total_width
    
    def _generate_frame_images(self, comments: list[dict], emoji_cache: dict, 
                             frame_count: int, fps: int) -> bool:
        """
        フレーム画像を並列生成
        
        Args:
            comments: 処理済みコメントリスト
            emoji_cache: 絵文字キャッシュ
            frame_count: 総フレーム数
            fps: フレームレート
            
        Returns:
            処理成功/失敗
        """
        try:
            # ✅ 既存チェック（最初のフレームが存在する場合スキップ）
            sample_frame_path = os.path.join(self.temp_dir, "000000.png")
            if os.path.exists(sample_frame_path):
                print(f"✓ フレーム画像が既に存在するためスキップ: {self.temp_dir}")
                return True
            # 一時ディレクトリを作成
            os.makedirs(self.temp_dir, exist_ok=True)
            
            # バッチサイズ設定
            batch_size = 100
            cpu_cores = min(cpu_count(), 8)  # 最大8コア使用
            
            print(f"フレーム数: {frame_count}, バッチサイズ: {batch_size}, CPUコア数: {cpu_cores}")
            
            # バッチを作成
            batches = []
            for i in range(0, frame_count, batch_size):
                batch_end = min(i + batch_size, frame_count)
                batches.append((i, batch_end))
            
            # 並列処理用の引数を準備
            process_args = []
            for batch_start, batch_end in batches:
                args = (batch_start, batch_end, comments, emoji_cache, fps, self.temp_dir)
                process_args.append(args)
            
            # 並列処理実行
            start_time = time.time()
            with Pool(processes=cpu_cores) as pool:
                results = pool.map(self._process_frame_batch, process_args)
            
            processing_time = time.time() - start_time
            print(f"フレーム生成完了: {processing_time:.2f}秒")
            
            # 全バッチが成功したかチェック
            return all(results)
            
        except Exception as e:
            print(f"フレーム生成エラー: {e}")
            return False
    
    @staticmethod
    def _process_frame_batch(args: tuple) -> bool:
        """
        フレームバッチを処理（並列処理用静的メソッド）
        
        Args:
            args: (batch_start, batch_end, comments, emoji_cache, fps, temp_dir)
            
        Returns:
            処理成功/失敗
        """
        batch_start, batch_end, comments, emoji_cache, fps, temp_dir = args
        
        try:
            frame_renderer = FrameRenderer()
            for frame_num in range(batch_start, batch_end):
                frame_time = frame_num / fps
                
                # アクティブなコメントを取得
                active_comments = VideoProcessor._get_active_comments(comments, frame_time)
                
                # オーバーレイ画像を生成
                overlay = frame_renderer.create_comment_overlay_image(
                    frame_time, active_comments, emoji_cache
                )
                
                # 画像を保存
                frame_path = os.path.join(temp_dir, f"{frame_num:06d}.png")
                overlay.save(frame_path, "PNG")
            
            return True
            
        except Exception as e:
            print(f"バッチ処理エラー ({batch_start}-{batch_end}): {e}")
            return False
    
    @staticmethod
    def _get_active_comments(comments: List[dict], frame_time: float, 
                           display_duration: float = 8.0) -> List[dict]:
        """
        指定時刻でアクティブなコメントを取得
        
        Args:
            comments: コメントリスト
            frame_time: フレーム時刻
            display_duration: コメント表示時間
            
        Returns:
            アクティブなコメントリスト
        """
        active_comments = []
        
        for comment in comments:
            start_time = comment['timestamp']
            end_time = start_time + display_duration
            
            if start_time <= frame_time <= end_time:
                active_comments.append(comment)
        
        return active_comments
    
    def _combine_video_with_frames(self, video_path: str, output_path: str, fps: int) -> bool:
        """
        動画とフレーム画像を合成
        
        Args:
            video_path: 入力動画パス
            output_path: 出力動画パス
            fps: フレームレート
            
        Returns:
            処理成功/失敗
        """
        try:
            # FFmpegコマンドを構築
            frame_pattern = os.path.join(self.temp_dir, "%06d.png")
            
            cmd = [
                'ffmpeg', '-y',  # 強制上書き
                '-i', video_path,  # 入力動画
                '-i', frame_pattern,  # 入力フレーム画像
                '-filter_complex', '[0:v][1:v]overlay=0:0:enable=\'between(t,0,999999)\'',  # オーバーレイ
                '-c:v',  'h264_nvenc',  # 動画コーデック
                '-c:a', 'copy',     # 音声コピー
                '-r', str(fps),     # フレームレート
                '-pix_fmt', 'yuv420p',  # ピクセルフォーマット
                output_path
            ]
            
            print(f"FFmpegコマンド実行: {' '.join(cmd)}")
            
            # FFmpeg実行
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("動画合成完了")
                return True
            else:
                print(f"FFmpegエラー: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"動画合成エラー: {e}")
            return False
    
    def _cleanup_temp_files(self) -> None:
        """一時ファイルをクリーンアップ"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                print("一時ファイルクリーンアップ完了")
        except Exception as e:
            print(f"クリーンアップエラー: {e}")

class ThumbnailCommentLaneManager:
    """サムネイル用コメントレーン管理クラス（既存クラスに影響を与えない）"""
    
    def __init__(self, max_lanes: int = 20):
        self.max_lanes = max_lanes
        self.lane_assignments = {}
    
    def assign_comment_lanes(self, comments: List[dict]) -> List[dict]:
        """
        コメントにレーン番号を割り当て（サムネイル用）
        
        Args:
            comments: コメントリスト
        
        Returns:
            List[dict]: レーン番号が追加されたコメントリスト
        """
        import copy
        import random
        
        comments_with_lanes = copy.deepcopy(comments)
        
        # ランダムにレーンを割り当て（重複OK）
        for i, comment in enumerate(comments_with_lanes):
            comment['lane'] = i % self.max_lanes  # 順番に配置して重複を許可
        
        return comments_with_lanes

class EmojiProcessor:
    """絵文字処理を管理するクラス"""
    
    def __init__(self, cache_base_dir: str = None):
        """
        絵文字プロセッサの初期化
        
        Args:
            cache_base_dir (str): 絵文字キャッシュのベースディレクトリ
        """
        # backend/emoji_cache ディレクトリにキャッシュを作成
        if cache_base_dir is None:
            base_dir = Path(__file__).parent / "emoji_cache"
        else:
            base_dir = Path(cache_base_dir)
        self.cache_base_dir = base_dir
        self.cache_base_dir.mkdir(exist_ok=True)
        self.unicode_cache_dir = self.cache_base_dir / "unicode"
        self.unicode_cache_dir.mkdir(exist_ok=True)

        
        # Unicode絵文字の正規表現パターン
        self.unicode_emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F]'  # 感情表現
            r'|[\U0001F300-\U0001F5FF]'  # その他のシンボル
            r'|[\U0001F680-\U0001F6FF]'  # 交通・地図
            r'|[\U0001F1E0-\U0001F1FF]'  # 国旗
            r'|[\U00002600-\U000026FF]'  # その他のシンボル
            r'|[\U00002700-\U000027BF]'  # 装飾文字
            r'|[\U0001F900-\U0001F9FF]'  # 補足シンボル
            r'|[\U0001FA70-\U0001FAFF]'  # 拡張シンボル
        )
        
        # YouTubeカスタム絵文字の正規表現パターン
        self.custom_emoji_pattern = re.compile(r':([^:]+):')


    def parse_comment_elements(self, text: str, emoji_dict: dict) -> List[dict]:
        """
        コメントをテキストと絵文字要素に分解
        
        Args:
            text (str): 解析するコメントテキスト
            emoji_dict (dict): YouTubeカスタム絵文字辞書
            
        Returns:
            List[dict]: 要素リスト
                各要素は以下の構造:
                - {"type": "text", "content": str}
                - {"type": "custom_emoji", "id": str, "url": str, "label": str}
                - {"type": "unicode_emoji", "content": str}
        """
        elements = []
        current_pos = 0
        
        # 全ての絵文字位置を検出
        emoji_positions = []
        
        # YouTubeカスタム絵文字を検出
        for match in self.custom_emoji_pattern.finditer(text):
            emoji_key = match.group(0)  # :EmojiName:
            emoji_name = match.group(1)  # EmojiName
            
            if emoji_key in emoji_dict:
                emoji_positions.append({
                    'start': match.start(),
                    'end': match.end(),
                    'type': 'custom_emoji',
                    'id': emoji_key,
                    'url': emoji_dict[emoji_key].get('url', ''),
                    'label': emoji_dict[emoji_key].get('label', emoji_name)
                })
        
        # Unicode絵文字を検出
        for match in self.unicode_emoji_pattern.finditer(text):
            emoji_positions.append({
                'start': match.start(),
                'end': match.end(),
                'type': 'unicode_emoji',
                'content': match.group(0)
            })
        
        # 位置順にソート
        emoji_positions.sort(key=lambda x: x['start'])
        
        # テキストと絵文字を順番に処理
        for emoji_info in emoji_positions:
            # 絵文字前のテキスト
            if current_pos < emoji_info['start']:
                text_content = text[current_pos:emoji_info['start']]
                if text_content:
                    elements.append({
                        'type': 'text',
                        'content': text_content
                    })
            
            # 絵文字要素を追加
            if emoji_info['type'] == 'custom_emoji':
                elements.append({
                    'type': 'custom_emoji',
                    'id': emoji_info['id'],
                    'url': emoji_info['url'],
                    'label': emoji_info['label']
                })
            else:  # unicode_emoji
                elements.append({
                    'type': 'unicode_emoji',
                    'content': emoji_info['content']
                })
            
            current_pos = emoji_info['end']
        
        # 残りのテキスト
        if current_pos < len(text):
            remaining_text = text[current_pos:]
            if remaining_text:
                elements.append({
                    'type': 'text',
                    'content': remaining_text
                })
        
        return elements

    def download_and_cache_emojis(self, emoji_dict: dict, channel_name: str) -> dict:
        """
        絵文字画像をダウンロード・キャッシュ
        
        Args:
            emoji_dict (dict): 絵文字辞書
            channel_name (str): チャンネル名（キャッシュディレクトリ識別用）
            
        Returns:
            dict: キャッシュされた絵文字の情報
                {emoji_id: {"path": str, "size": tuple, "success": bool}}
        """
        # チャンネル用キャッシュディレクトリ作成
        sanitized_channel = sanitize_filename(channel_name)
        cache_dir = self.cache_base_dir / sanitized_channel
        cache_dir.mkdir(exist_ok=True)
        
        emoji_cache = {}
        cache_info_file = cache_dir / "cache_info.json"
        
        # 既存キャッシュ情報を読み込み
        if cache_info_file.exists():
            try:
                with open(cache_info_file, 'r', encoding='utf-8') as f:
                    emoji_cache = json.load(f)
                logger.info(f"既存キャッシュ情報を読み込み: {len(emoji_cache)}個")
            except Exception as e:
                logger.warning(f"キャッシュ情報読み込みエラー: {e}")
                emoji_cache = {}
        
        # 新しい絵文字をダウンロード
        downloaded_count = 0
        failed_count = 0
        
        for emoji_id, emoji_info in emoji_dict.items():
            # 既にキャッシュされているかチェック
            if emoji_id in emoji_cache and emoji_cache[emoji_id].get('success', False):
                cache_path = cache_dir / emoji_cache[emoji_id]['path']
                if cache_path.exists():
                    continue
            
            url = emoji_info.get('url', '')
            if not url:
                logger.warning(f"絵文字 {emoji_id} のURLが見つかりません")
                emoji_cache[emoji_id] = {
                    'path': '',
                    'size': (0, 0),
                    'success': False,
                    'error': 'URL not found'
                }
                failed_count += 1
                continue
            
            try:
                # ファイル名生成（URLハッシュベース）
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
                safe_name = sanitize_filename(emoji_info.get('label', emoji_id.strip(':')))
                filename = f"{safe_name}_{url_hash}.png"
                file_path = cache_dir / filename
                
                # ダウンロード実行
                logger.info(f"絵文字ダウンロード中: {emoji_id} -> {filename}")
                
                response = requests.get(url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                
                # 画像として保存・検証
                with Image.open(BytesIO(response.content)) as img:
                    img.save(file_path, 'PNG')
                    
                    emoji_cache[emoji_id] = {
                        'path': filename,
                        'size': img.size,
                        'success': True,
                        'download_time': time.time()
                    }
                    downloaded_count += 1
                    
                # ダウンロード間隔を空ける
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"絵文字 {emoji_id} のダウンロードエラー: {e}")
                emoji_cache[emoji_id] = {
                    'path': '',
                    'size': (0, 0),
                    'success': False,
                    'error': str(e)
                }
                failed_count += 1
        
        # キャッシュ情報を保存
        try:
            with open(cache_info_file, 'w', encoding='utf-8') as f:
                json.dump(emoji_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"キャッシュ情報保存エラー: {e}")
        
        logger.info(f"絵文字キャッシュ完了: ダウンロード={downloaded_count}, 失敗={failed_count}")
        return emoji_cache

    def get_emoji_image(self, emoji_id: str, emoji_cache: dict, channel_name: str, 
                       target_size: tuple = (36, 36)) -> Optional[Image.Image]:
        """
        キャッシュから絵文字画像を取得
        
        Args:
            emoji_id (str): 絵文字ID
            emoji_cache (dict): 絵文字キャッシュ情報
            channel_name (str): チャンネル名
            target_size (tuple): リサイズ後のサイズ (width, height)
            
        Returns:
            Optional[Image.Image]: 絵文字画像（RGBA形式）、失敗時はNone
        """
        if emoji_id not in emoji_cache or not emoji_cache[emoji_id].get('success', False):
            return None
        
        try:
            sanitized_channel = sanitize_filename(channel_name)
            cache_dir = self.cache_base_dir / sanitized_channel
            image_path = cache_dir / emoji_cache[emoji_id]['path']
            
            if not image_path.exists():
                logger.warning(f"絵文字画像ファイルが見つかりません: {image_path}")
                return None
            
            # 画像を読み込み・リサイズ（拡大も可能に修正）
            with Image.open(image_path) as img:
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')


                # リサイズキャッシュの保存先
                resized_dir = self.cache_base_dir / sanitized_channel / "custom_emoji"
                resized_dir.mkdir(parents=True, exist_ok=True)
                resized_filename = f"{emoji_id.strip(':')}_{target_size[0]}x{target_size[1]}.png"
                resized_path = resized_dir / resized_filename

                # 既にリサイズ済みファイルがあればそれを返す
                if resized_path.exists():
                    try:
                        with Image.open(resized_path) as cached_img:
                            return cached_img.copy()
                    except Exception as e:
                        logger.warning(f"リサイズ済み絵文字画像の読み込み失敗: {resized_path} {e}")
                        # 壊れたキャッシュファイルを削除し、再生成を試みる
                        try:
                            resized_path.unlink()
                            logger.info(f"壊れたキャッシュファイルを削除: {resized_path}")
                        except Exception as del_e:
                            logger.warning(f"壊れたキャッシュファイルの削除失敗: {resized_path} {del_e}")
                        # 続行して新たにリサイズ＆保存
                        # 壊れたキャッシュは削除
                        try:
                            resized_path.unlink()
                        except Exception:
                            pass

                # 拡大・縮小どちらもresizeで対応
                resized_img = img.resize(target_size, Image.Resampling.LANCZOS)
                final_img = Image.new('RGBA', target_size, (0, 0, 0, 0))
                x_offset = (target_size[0] - resized_img.width) // 2
                y_offset = (target_size[1] - resized_img.height) // 2
                final_img.paste(resized_img, (x_offset, y_offset), resized_img)

                # リサイズ済み画像をキャッシュ保存（原子的に保存）
                import tempfile
                import os
                try:
                    with tempfile.NamedTemporaryFile(delete=False, dir=resized_dir, suffix=".png") as tmpfile:
                        tmp_path = tmpfile.name
                        final_img.save(tmp_path, 'PNG')
                    os.replace(tmp_path, resized_path)  # 原子的にリネーム
                except Exception as e:
                    logger.warning(f"リサイズ済み絵文字画像の保存失敗: {resized_path} {e}")

                return final_img

                
        except Exception as e:
            logger.error(f"絵文字画像取得エラー {emoji_id}: {e}")
            return None

    def create_unicode_emoji_image(self, emoji_char: str, font_size: int = 36) -> Optional[Image.Image]:
        try:
            # キャッシュファイル名を生成
            filename = f"{'-'.join(f'{ord(c):X}' for c in emoji_char)}_{font_size}.png"
            filepath = self.unicode_cache_dir / filename

            # キャッシュが存在すれば読み込んで返す
            if filepath.exists():
                try:
                    return Image.open(filepath).convert("RGBA")
                except Exception as e:
                    logger.warning(f"キャッシュ読み込み失敗 {filename}: {e}")
            
            # ↓ 通常通り描画処理（元の処理ここから）↓

            img = Image.new('RGBA', (font_size, font_size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            font = None
            font_paths = [
                "C:/Windows/Fonts/seguiemj.ttf", 
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        font = ImageFont.truetype(font_path, font_size)
                        break
                    except:
                        continue
            if font is None:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), emoji_char, font=font)
            x = (font_size - (bbox[2] - bbox[0])) // 2
            y = (font_size - (bbox[3] - bbox[1])) // 2
            draw.text((x, y), emoji_char, font=font, fill=(255, 255, 255, 255))

            # 作成した画像をキャッシュに保存
            try:
                img.save(filepath, format='PNG')
            except Exception as e:
                logger.warning(f"キャッシュ保存失敗 {filename}: {e}")

            return img

        except Exception as e:
            logger.error(f"Unicode絵文字画像生成エラー {emoji_char}: {e}")
            return None
        
class CommentLaneManager:
    """コメントのレーン割り当てを管理するクラス"""
    
    def __init__(self, max_lanes: int = 10, display_duration: float = 8.0):
        """
        初期化
        
        Args:
            max_lanes: 最大レーン数
            display_duration: コメント表示時間（秒）
        """
        self.max_lanes = max_lanes
        self.display_duration = display_duration
        self.lane_last_used = {}  # lane_id -> last_end_time
    
    def assign_comment_lanes(self, comments: List[dict]) -> List[dict]:
        """
        コメントにレーン番号を割り当て（衝突回避）
        
        Args:
            comments: コメントリスト（各要素は timestamp, text, author などを含む）
        
        Returns:
            List[dict]: レーン番号が追加されたコメントリスト
        """
        # コメントをコピーして破壊的変更を防ぐ
        comments_with_lanes = copy.deepcopy(comments)
        
        # レーン使用状況をリセット
        self.lane_last_used = {}
        
        # 時間順にソート（早い順）
        comments_with_lanes.sort(key=lambda x: x['timestamp'])
        
        for comment in comments_with_lanes:
            start_time = comment['timestamp']
            end_time = start_time + self.display_duration
            
            # 最適なレーンを見つける
            assigned_lane = self._find_available_lane(start_time)
            
            # レーン情報を追加
            comment['lane'] = assigned_lane
            comment['start_time'] = start_time
            comment['end_time'] = end_time
            
            # レーン使用状況を更新
            self.lane_last_used[assigned_lane] = end_time
        
        return comments_with_lanes
    
    def _find_available_lane(self, start_time: float) -> int:
        import random
        
        # 利用可能なレーンを全て収集
        available_lanes = []
        for lane in range(self.max_lanes):
            if lane not in self.lane_last_used or self.lane_last_used[lane] <= start_time:
                available_lanes.append(lane)
        
        if available_lanes:
            # 80%の確率でランダム選択、20%の確率で最初の空きレーンを選択
            if random.random() < 0.8:
                return random.choice(available_lanes)
            else:
                return available_lanes[0]  # 順序通りの選択も時々混ぜる
        
        # 全レーンが埋まっている場合の改良
        # 最も早く終了するレーン群からランダム選択
        min_end_time = min(self.lane_last_used.values())
        earliest_lanes = [lane for lane, end_time in self.lane_last_used.items() 
                         if end_time <= min_end_time + 0.5]  # 0.5秒の余裕
        
        return random.choice(earliest_lanes)
    
    def get_active_comments_at_time(self, comments: List[dict], frame_time: float) -> List[dict]:
        """
        指定時刻でアクティブなコメントを取得
        
        Args:
            comments: レーン割り当て済みコメントリスト
            frame_time: 対象フレーム時刻
        
        Returns:
            List[dict]: アクティブなコメントリスト
        """
        active_comments = []
        
        for comment in comments:
            if comment['start_time'] <= frame_time <= comment['end_time']:
                active_comments.append(comment)
        
        return active_comments
    
    def calculate_comment_position(self, comment: dict, frame_time: float, 
                                 video_width: int, video_height: int) -> dict:
        """
        指定時刻でのコメント位置を計算
        
        Args:
            comment: コメント情報（lane, start_time, end_time を含む）
            frame_time: 現在のフレーム時刻
            video_width: 動画幅
            video_height: 動画高さ
        
        Returns:
            dict: 位置情報（x, y, lane, progress）
        """
        # コメントの進行度を計算（0.0 ~ 1.0）
        progress = (frame_time - comment['start_time']) / self.display_duration
        progress = max(0.0, min(1.0, progress))  # 0-1の範囲に制限
        
        # X座標計算（右から左へ移動）
        # 画面右端からコメント全体が左端まで移動
        comment_width = self._estimate_comment_width(comment)
        start_x = video_width
        end_x = -comment_width
        x = start_x + (end_x - start_x) * progress
        
        # Y座標計算（上540ピクセルの範囲に確実に配置）
        upper_area = 540  
        lane_height = upper_area / self.max_lanes
        y = int(comment['lane'] * lane_height)  # レーン0が一番上、レーン7が上1/3の下端付近
        
        return {
            'x': int(x),
            'y': int(y),
            'lane': comment['lane'],
            'progress': progress,
            'visible': 0.0 <= progress <= 1.0
        }
    
    def _estimate_comment_width(self, comment: dict, font_size: int = 36, 
                               emoji_width: int = 36) -> int:
        """
        コメントの表示幅を推定
        
        Args:
            comment: コメント情報
            font_size: フォントサイズ
            emoji_width: 絵文字幅
        
        Returns:
            int: 推定幅（ピクセル）
        """
        text = comment.get('text', '')
        
        # 簡易的な文字数ベース計算
        # 実際のフォント幅は使用時に正確に計算する
        char_count = len(text)
        
        # 絵文字を考慮した幅計算（簡易版）
        # :emoji: 形式の絵文字をカウント
        emoji_count = text.count(':') // 2
        
        # ASCII文字: font_size * 0.6, 日本語: font_size * 1.0, 絵文字: emoji_width
        estimated_width = (char_count - emoji_count * 8) * font_size * 0.8 + emoji_count * emoji_width
        
        return max(int(estimated_width), 100)  # 最小幅100px


def assign_comment_lanes(comments: List[dict], max_lanes: int = 10, 
                        display_duration: float = 8.0) -> List[dict]:
    """
    コメントにレーン番号を割り当て（衝突回避）
    
    Args:
        comments: コメントリスト
        max_lanes: 最大レーン数
        display_duration: コメント表示時間（秒）
    
    Returns:
        List[dict]: レーン番号が追加されたコメントリスト
    """
    manager = CommentLaneManager(max_lanes, display_duration)
    return manager.assign_comment_lanes(comments)


def calculate_comment_positions(comments: List[dict], frame_time: float,
                               video_width: int = 1920, video_height: int = 1080,
                               display_duration: float = 8.0) -> List[dict]:
    """
    指定時刻でのアクティブコメント位置を計算
    
    Args:
        comments: レーン割り当て済みコメントリスト
        frame_time: 対象フレーム時刻
        video_width: 動画幅
        video_height: 動画高さ
        display_duration: コメント表示時間
    
    Returns:
        List[dict]: 位置情報付きアクティブコメントリスト
    """
    manager = CommentLaneManager(display_duration=display_duration)
    
    # アクティブなコメントを取得
    active_comments = manager.get_active_comments_at_time(comments, frame_time)
    
    # 各コメントの位置を計算
    positioned_comments = []
    for comment in active_comments:
        position = manager.calculate_comment_position(
            comment, frame_time, video_width, video_height
        )
        
        # コメント情報と位置情報をマージ
        comment_with_position = {**comment, **position}
        positioned_comments.append(comment_with_position)

        # print(f"[DEBUG] comment['lane'={comment['lane']}")
    
    return positioned_comments

