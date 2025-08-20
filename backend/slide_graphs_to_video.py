import subprocess
import os

def add_sliding_graphs_to_video(
    input_video_path,
    graphs_image_path,
    output_video_path,
    slide_height=656.25,
    slide_y=1263.75,
    duration=35.0,
    video_width=1080,
    video_height=1920
):
    """
    input_video_path: 9:16動画パス
    graphs_image_path: 横長グラフ画像パス
    output_video_path: 合成後の出力パス
    slide_height: スライド画像の高さ（下スペースの高さ）
    slide_y: スライド画像のY座標（下スペースの上端）
    duration: スライドアニメーションの秒数
    video_width, video_height: 動画サイズ
    """
    # 横長画像の幅を取得
    from PIL import Image
    img = Image.open(graphs_image_path)
    img_width, img_height = img.size
    # スライド距離
    start_x = video_width
    end_x = -img_width
    # ffmpeg filter_complexでスライド合成
    filter_complex = (
        f"[1:v]scale={img_width}:{slide_height}[slide]; "
        f"[0:v][slide]overlay=x='if(lte(t,{duration}),{start_x}-(t/{duration})*({start_x - end_x}),{end_x})':y={slide_y}:shortest=1"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_video_path,
        "-loop", "1", "-i", graphs_image_path,
        "-filter_complex", filter_complex,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-shortest",
        output_video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg合成失敗: {result.stderr}")
    return output_video_path
