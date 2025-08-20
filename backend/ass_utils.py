import os
import tempfile
import subprocess
from pathlib import Path
import whisper

def create_ass_file(subtitle_data, ass_path, creator_name, style=None):
    """
    Create an ASS subtitle file from subtitle_data.
    subtitle_data: list of dicts with at least 'text', 'start', 'end' (seconds)
    ass_path: output file path
    creator_name: for style selection
    style: dict with font_name, font_size, outline_width, font_color, outline_color (optional)
    """
    # Style defaults
    if style is None:
        style = {}
    font_name = style.get("font_name", "Arial")
    font_size = style.get("font_size", 48)
    outline_width = style.get("outline_width", 8)
    primary_font_color = style.get("font_color", "&H00FFFFFF")
    ass_outline_color = style.get("outline_color", "&H00000000")

    header = f"""[Script Info]\nTitle: Clip Subtitles\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: None\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font_name},{font_size},{primary_font_color},&H000000FF,{ass_outline_color},&H00000000,1,0,0,0,100,100,0,0,1,{outline_width},0,7,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    def sec_to_ass_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int((sec - int(sec)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    dialogue_lines = []
    for info in subtitle_data:
        start_time = sec_to_ass_time(info.get('start', 0))
        end_time = sec_to_ass_time(info.get('end', info.get('start', 0) + 8))
        # 個別スタイル取得
        line_font_size = info.get('font_size', font_size)
        line_pos = info.get('pos', None)
        line_align = info.get('align', 7)
        line_font_name = info.get('font_name', font_name)
        line_font_color = info.get('font_color', primary_font_color)
        line_outline_color = info.get('outline_color', ass_outline_color)
        # ASSタグ組み立て
        effect_tags = [
            f"\\fn{line_font_name}",
            f"\\fs{line_font_size}",
            f"\\bord{outline_width}",
            f"\\an{line_align}",
            f"\\c{line_font_color}",
            f"\\3c{line_outline_color}",
            "\\fad(1000,1000)"
        ]
        if line_pos:
            effect_tags.append(f"\\pos({line_pos})")
        effect = "{" + ''.join(effect_tags) + "}"
        text = info['text']
        dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{effect}{text}"
        dialogue_lines.append(dialogue_line)

    with open(ass_path, 'w', encoding='utf-8', newline='') as f:
        f.write(header)
        if dialogue_lines:
            f.write("\n".join(dialogue_lines))
        f.flush()
        os.fsync(f.fileno())
    return ass_path

def create_ass_file_whisper(subtitle_data, ass_path, creator_name, style=None):
    """
    Create an ASS subtitle file from subtitle_data.
    subtitle_data: list of dicts with at least 'text', 'start', 'end' (seconds)
    ass_path: output file path
    creator_name: for style selection
    style: dict with font_name, font_size, outline_width, font_color, outline_color (optional)
    """
    # Style defaults
    if style is None:
        style = {}
    font_name = style.get("font_name", "Arial")
    font_size = style.get("font_size", 48)
    outline_width = style.get("outline_width", 8)
    primary_font_color = style.get("font_color", "&H00FFFFFF")
    ass_outline_color = style.get("outline_color", "&H00000000")

    header = f"""[Script Info]\nTitle: Clip Subtitles\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: None\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font_name},{font_size},{primary_font_color},&H000000FF,{ass_outline_color},&H00000000,1,0,0,0,100,100,0,0,1,{outline_width},0,7,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    def sec_to_ass_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int((sec - int(sec)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    dialogue_lines = []
    for info in subtitle_data:
        start_time = sec_to_ass_time(info.get('start', 0))
        end_time = sec_to_ass_time(info.get('end', info.get('start', 0) + 8))
        # 個別スタイル取得
        line_font_size = info.get('font_size', font_size)
        line_pos = info.get('pos', None)
        line_align = info.get('align', 7)
        line_font_name = info.get('font_name', font_name)
        line_font_color = info.get('font_color', primary_font_color)
        line_outline_color = info.get('outline_color', ass_outline_color)
        # ASSタグ組み立て
        effect_tags = [
            f"\\fn{line_font_name}",
            f"\\fs{line_font_size}",
            f"\\bord{outline_width}",
            f"\\an{line_align}",
            f"\\c{line_font_color}",
            f"\\3c{line_outline_color}"
        ]
        if line_pos:
            effect_tags.append(f"\\pos({line_pos})")
        effect = "{" + ''.join(effect_tags) + "}"
        text = info['text']
        dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{effect}{text}"
        dialogue_lines.append(dialogue_line)

    with open(ass_path, 'w', encoding='utf-8', newline='') as f:
        f.write(header)
        if dialogue_lines:
            f.write("\n".join(dialogue_lines))
        f.flush()
        os.fsync(f.fileno())
    return ass_path

def create_ass_file_9x16(subtitle_data, ass_path, creator_name, style=None):
    """
    Create an ASS subtitle file from subtitle_data.
    subtitle_data: list of dicts with at least 'text', 'start', 'end' (seconds)
    ass_path: output file path
    creator_name: for style selection
    style: dict with font_name, font_size, outline_width, font_color, outline_color (optional)
    """
    # Style defaults
    if style is None:
        style = {}
    font_name = style.get("font_name", "Arial")
    font_size = style.get("font_size", 48)
    outline_width = style.get("outline_width", 8)
    primary_font_color = style.get("font_color", "&H00FFFFFF")
    ass_outline_color = style.get("outline_color", "&H00000000")

    header = f"""[Script Info]\nTitle: Clip Subtitles\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: None\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font_name},{font_size},{primary_font_color},&H000000FF,{ass_outline_color},&H00000000,1,0,0,0,100,100,0,0,1,{outline_width},0,7,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""

    def sec_to_ass_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int((sec - int(sec)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    dialogue_lines = []
    for info in subtitle_data:
        start_time = sec_to_ass_time(info.get('start', 0))
        end_time = sec_to_ass_time(info.get('end', info.get('start', 0) + 8))
        # 個別スタイル取得
        line_font_size = info.get('font_size', font_size)
        line_pos = info.get('pos', None)
        line_align = info.get('align', 7)
        line_font_name = info.get('font_name', font_name)
        line_font_color = info.get('font_color', primary_font_color)
        line_outline_color = info.get('outline_color', ass_outline_color)
        # ASSタグ組み立て
        effect_tags = [
            f"\\fn{line_font_name}",
            f"\\fs{line_font_size}",
            f"\\bord{outline_width}",
            f"\\an{line_align}",
            f"\\c{line_font_color}",
            f"\\3c{line_outline_color}",
            "\\fad(1000,1000)"
        ]
        if line_pos:
            effect_tags.append(f"\\pos({line_pos})")
        effect = "{" + ''.join(effect_tags) + "}"
        text = info['text']
        dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{effect}{text}"
        dialogue_lines.append(dialogue_line)

    with open(ass_path, 'w', encoding='utf-8', newline='') as f:
        f.write(header)
        if dialogue_lines:
            f.write("\n".join(dialogue_lines))
        f.flush()
        os.fsync(f.fileno())
    return ass_path

def combine_video_and_ass(video_path, ass_path, output_path):
    """
    Use ffmpeg to mux video and ASS subtitle.
    """
    if os.path.exists(output_path):
        os.remove(output_path)

    video_path_abs = Path(video_path).resolve()
    ass_path_abs = Path(ass_path).resolve()
    output_path_abs = Path(output_path).resolve()

    work_dir = ass_path_abs.parent
    video_rel = os.path.relpath(video_path_abs, work_dir)
    ass_rel = ass_path_abs.name
    output_rel = os.path.relpath(output_path_abs, work_dir)

    original_cwd = os.getcwd()
    try:
        os.chdir(work_dir)
        command = [
            'ffmpeg',
            '-loglevel', 'error',
            '-i', video_rel,
            '-vf', f'ass={ass_rel}',
            '-c:a', 'copy',
            '-y',
            output_rel
        ]
        subprocess.run(command, check=True)
    finally:
        os.chdir(original_cwd)
    return str(output_path_abs)

def add_ass_subtitles_to_ed(
    ed_video_path: str,
    output_path: str,
    archive_time: str,
    total_comments: int,
    max_comments_10s: int,
    avg_comments_1h: int
):
    """
    ED動画に指定のASS字幕を追加して出力する。
    """
    # 字幕情報
    # 縁取り色を黒（ASS色コード: &H00000000）に統一
    outline_color_black = '&H00000000'
    subtitle_data = [
        {
            'text': f' {archive_time}',
            'start': 2,
            'end': 15,
            'pos': '1045,174',
            'font_name': 'ラノベPOP v2',
            'font_size': 190,
            'font_color': '&H00FFFFFF',  # 白
            'outline_color': outline_color_black,  # 黒
            'align': 7,
        },
        {
            'text': f' {total_comments} 件',
            'start': 4,
            'end': 15,
            'pos': '1045,403',
            'font_name': 'ラノベPOP v2',
            'font_size': 190,
            'font_color': '&H00FFFFFF',
            'outline_color': outline_color_black,
            'align': 7,
        },
        {
            'text': f' {max_comments_10s} 件/10s',
            'start': 6,
            'end': 15,
            'pos': '1045,632',
            'font_name': 'ラノベPOP v2',
            'font_size': 190,
            'font_color': '&H00FFFFFF',
            'outline_color': outline_color_black,
            'align': 7,
        },
        {
            'text': f' {avg_comments_1h} 件/1h',
            'start': 8,
            'end': 15,
            'pos': '1045,859',
            'font_name': 'ラノベPOP v2',
            'font_size': 190,
            'font_color': '&H00FFFFFF',
            'outline_color': outline_color_black,
            'align': 7,
        },
    ]
    # ASSファイル一時パス
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        ass_path = os.path.join(tmpdir, 'ed_subtitles.ass')
        # print(f"[DEBUG] add_ass_subtitles_to_ed: tmpdir={tmpdir}")
        # print(f"[DEBUG] add_ass_subtitles_to_ed: ass_path={ass_path}")
        try:
            create_ass_file(subtitle_data, ass_path, creator_name="ED", style={
                'font_name': 'ラノベPOP v2',
                'font_size': 190,
                'outline_width': 7,
                'font_color': '&H00FFFFFF',
                'outline_color': '&H00000000',
            })
            # print(f"[DEBUG] add_ass_subtitles_to_ed: ASSファイル作成済み? {os.path.exists(ass_path)}")
            # if os.path.exists(ass_path):
            #     with open(ass_path, 'r', encoding='utf-8') as f:
            #         print(f"[DEBUG] add_ass_subtitles_to_ed: ASSファイル内容:\n" + f.read())
        except Exception as e:
            print(f"[ERROR] add_ass_subtitles_to_ed: ASSファイル作成失敗: {e}")
            import traceback
            traceback.print_exc()
            raise
        try:
            combine_video_and_ass(ed_video_path, ass_path, output_path)
        except Exception as e:
            print(f"[ERROR] add_ass_subtitles_to_ed: combine_video_and_ass失敗: {e}")
            import traceback
            traceback.print_exc()
            raise
    return output_path

def run_whisper_on_video(video_path: str, model_size: str = "large", language: str = None, 
                         pause_threshold: float = 0.2, max_chars: int = 40, video_speed: float = 0.85) -> list:
    """
    Whisperで動画ファイルを音声認識し、音声の間と文字数制限で分割された字幕セグメントを返す。
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        slowed_path = os.path.join(tmpdir, "slowed.mp4")

        # スロー化（音声video_speed倍＋映像同期）
        cmd_slow = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex", f"[0:a]atempo={video_speed}[a];[0:v]setpts=PTS/{video_speed}[v]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-c:a", "aac",
            slowed_path
        ]
        subprocess.run(cmd_slow, check=True)

        # slowed.mp4 から音声抽出（人声帯域をブースト＋コンプレッサー）
        audio_path = os.path.join(tmpdir, "audio_boosted.wav")
        # 人声帯域をブーストしつつ全体をコンプレッサーで持ち上げ
        eq_filter = (
            "equalizer=f=1000:t=q:w=2:g=10,"  # 中域
            "equalizer=f=300:t=q:w=2:g=8,"    # 低域
            "equalizer=f=3000:t=q:w=2:g=8,"   # 高域
            "acompressor=threshold=-30dB:ratio=6:attack=20:release=250"
        )
        cmd_audio = [
            "ffmpeg", "-y", "-i", slowed_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            "-af", eq_filter,
            audio_path
        ]
        subprocess.run(cmd_audio, check=True)

        # Whisper呼び出し（word timestamps 有効）
        model = whisper.load_model(model_size, device="cuda")
        result = model.transcribe(audio_path, verbose=False, language=language, word_timestamps=True)

    # word-level分割
    words = []
    for seg in result["segments"]:
        for word in seg.get("words", []):
            words.append(word)

    # ポーズ（単語間の間隔）で分割
    segments = []
    buffer = []
    last_end = None
    for i, word in enumerate(words):
        start = word["start"] * video_speed
        end = word["end"] * video_speed
        if buffer:
            # 前の単語のendと今の単語のstartの差がpause_thresholdより大きければ分割
            prev_end = buffer[-1]["end"] * video_speed
            if start - prev_end > pause_threshold:
                seg_end = prev_end
                segments.append({
                    "start": buffer[0]["start"] * video_speed,
                    "end": seg_end,
                    "text": "".join(w["word"] for w in buffer),
                    "avg_logprob": sum(w.get("prob", 0) for w in buffer) / len(buffer)
                })
                buffer = []
        buffer.append(word)
        last_end = end
        # max_chars分割
        text_len = sum(len(w["word"]) for w in buffer)
        if text_len > max_chars:
            seg_end = buffer[-1]["end"] * video_speed
            segments.append({
                "start": buffer[0]["start"] * video_speed,
                "end": seg_end,
                "text": "".join(w["word"] for w in buffer),
                "avg_logprob": sum(w.get("prob", 0) for w in buffer) / len(buffer)
            })
            buffer = []
            last_end = None
    # 最後の残り
    if buffer:
        seg_end = buffer[-1]["end"] * video_speed
        segments.append({
            "start": buffer[0]["start"] * video_speed,
            "end": seg_end,
            "text": "".join(w["word"] for w in buffer),
            "avg_logprob": sum(w.get("prob", 0) for w in buffer) / len(buffer)
        })

    # avg_logprobによるスキップ判定
    filtered_segments = [seg for seg in segments if seg.get("avg_logprob", 0) >= -1.5]
    return filtered_segments



def whisper_segments_to_ass_data(segments: list, style: dict) -> list:
    """
    WhisperのsegmentsリストをASS字幕用データリストに変換。
    style: ASS字幕のスタイル(dict)
    """
    ass_data = []
    for seg in segments:
        ass_data.append({
            "text": seg["text"],
            "start": seg["start"],
            "end": seg["end"],
            "font_name": style.get("font_name"),
            "font_size": style.get("font_size"),
            "font_color": style.get("font_color"),
            "outline_color": style.get("outline_color"),
            "align": style.get("align", 2),
        })
    return ass_data

def create_ass_from_whisper(video_path: str, ass_path: str, style: dict, model_size: str = "large", language: str = None) -> str:
    """
    動画ファイルからWhisperでASS字幕ファイルを生成。
    """
    # model_size引数は無視し、large/cudaで実行
    segments = run_whisper_on_video(video_path, model_size="large", language=language)
    ass_data = whisper_segments_to_ass_data(segments, style)
    create_ass_file_whisper(ass_data, ass_path, creator_name="Whisper", style=style)
    return ass_path
