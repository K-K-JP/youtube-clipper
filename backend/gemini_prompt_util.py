def regenerate_gemini_prompt_and_data(draw_comments, channel_name, video_id, rank, base_dir='backend/clips'):
    """
    指定rankのコメントのみでGemini用json/txtを生成し保存する（部分再生成用）。
    戻り値: (gemini_prompt_path, gemini_prompt_txt_path)
    """
    # rankでフィルタ＋スコア0または1のコメントからランダム抽出（select_gemini_commentsを再利用）
    try:
        rank_str = str(int(float(rank)))
    except Exception:
        rank_str = str(rank)
    selected = select_gemini_comments(draw_comments, max_per_rank=20)
    filtered = selected.get(rank_str, [])
    # Gemini用データ
    gemini_prompt_data = []
    for com in filtered:
        gemini_prompt_data.append({
            "clip_rank": rank_str,
            "text": com.get("text", "")
        })
    channel_dir = os.path.join(base_dir, sanitize_filename(channel_name))
    video_specific_dir = os.path.join(channel_dir, video_id)
    os.makedirs(video_specific_dir, exist_ok=True)
    gemini_prompt_path = os.path.join(video_specific_dir, f"gemini_prompt_rank{rank_str}.json")
    with open(gemini_prompt_path, 'w', encoding='utf-8') as f:
        json.dump(gemini_prompt_data, f, ensure_ascii=False, indent=2)
    gemini_prompt_text = '''
次の情報は、動画の切り抜きクリップに対応したコメントデータです。各コメントは「clip_rank」と「text」というキーを持ち、clip_rankはそのコメントがどのクリップ（順位）に属しているかを表します。

指定されたclip_rank（{rank}）について、そのクリップを代表するような「一言コメント」の候補を5つ出してください。
この一言は、実際にその場のコメント欄で誰かが言ってそうな自然なトーンの短文である必要があります。  
セリフっぽいもの、ツッコミ、感嘆、賞賛、ツイート風のリアクションなど、場面の雰囲気を一言で表すようなセリフを意識してください。

【制約】
- 指定clip_rankについて一言コメントを5つ出すこと
- コメントのtextすべてを使う必要はありません。ランダムに数個ピックアップし、それを参考にして一言を作ってください
- コメントに「::」が含まれている場合は、そのコメントは無視してください
- 出力は必ず以下のようなJSON形式で返してください（keyはclip_rank、valueは一言リスト）：

```
{{
  "{rank}": ["一言1", "一言2", "一言3", "一言4", "一言5"]
}}
```

上記ルールに従って、以下のデータをもとに一言を出力してください。
'''.replace("{rank}", rank_str)
    gemini_prompt_txt_path = os.path.join(video_specific_dir, f"gemini_prompt_rank{rank_str}.txt")
    with open(gemini_prompt_txt_path, 'w', encoding='utf-8') as f:
        f.write(gemini_prompt_text)
        f.write("\nコメントデータ:\n")
        json.dump(gemini_prompt_data, f, ensure_ascii=False, indent=2)
    return gemini_prompt_path, gemini_prompt_txt_path

def parse_gemini_output(gemini_output_path, rank):
    """
    Gemini出力(json or code block)から指定rankの一言リストのみを返す（保存はしない）。
    戻り値: [一言1, ...]（5件、なければ空文字で埋める）
    """
    import re
    rank_str = str(rank)
    try:
        with open(gemini_output_path, 'r', encoding='utf-8') as f:
            gemini_data = f.read()
        # コードブロックで囲まれている場合は中身だけ抽出
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", gemini_data, re.DOTALL)
        if match:
            gemini_data = match.group(1)
    except Exception as e:
        print(f"[ERROR] Gemini出力ファイルの読み込みに失敗: {e}")
        return ["（一言なし）"] * 5
    try:
        data = json.loads(gemini_data)
    except Exception as e:
        print(f"[ERROR] Gemini出力のJSONパースに失敗: {e}")
        return ["（一言なし）"] * 5
    num_required = 5
    default_msg = "（一言なし）"
    one_liners = []
    if isinstance(data, dict):
        # rankがfloat/intで出てくる場合もあるので正規化
        for k, v in data.items():
            try:
                norm_k = str(int(float(k)))
            except Exception:
                norm_k = str(k)
            if norm_k == rank_str:
                if isinstance(v, list):
                    one_liners = [str(x) if isinstance(x, str) else default_msg for x in v]
                else:
                    one_liners = []
                break
    # 5件未満なら埋める
    if len(one_liners) < num_required:
        one_liners += [default_msg] * (num_required - len(one_liners))
    elif len(one_liners) > num_required:
        one_liners = one_liners[:num_required]
    return one_liners
import os
import json
import random
from collections import defaultdict
from utility import sanitize_filename

def select_gemini_comments(draw_comments, max_per_rank=10):
    """
    draw_commentsからclip_rankごとにscoreが0または1のコメントを最大max_per_rank件ランダム抽出
    戻り値: {clip_rank: [コメントdict, ...], ...}
    """
    grouped = defaultdict(list)
    for c in draw_comments:
        # rankを必ずint(float)→strで正規化
        if 'clip_rank' in c:
            try:
                rank = str(int(float(c.get('clip_rank'))))
            except Exception:
                rank = str(c.get('clip_rank'))
        else:
            rank = None
        # chaos_score, healing_score, laugh_score の最大値が1以下なら抽出
        chaos = c.get('chaos_score', 0)
        healing = c.get('healing_score', 0)
        laugh = c.get('laugh_score', 0)
        max_score = max(chaos, healing, laugh)
        if rank is not None and max_score <= 1:
            grouped[rank].append(c)
    result = {}
    for rank, comments in grouped.items():
        if len(comments) > max_per_rank:
            result[rank] = random.sample(comments, max_per_rank)
        else:
            result[rank] = comments
    return result

def save_gemini_prompt_and_data(draw_comments_all, channel_name, video_id, base_dir='backend/clips'):
    """
    Gemini用コメントjsonとプロンプトtxtを所定のディレクトリに保存
    """
    gemini_selected = select_gemini_comments(draw_comments_all, 20)
    gemini_prompt_data = []
    for rank, comments in gemini_selected.items():
        for com in comments:
            gemini_prompt_data.append({
                "clip_rank": str(rank),
                "text": com.get("text", "")
            })
    channel_dir = os.path.join(base_dir, sanitize_filename(channel_name))
    video_specific_dir = os.path.join(channel_dir, video_id)
    os.makedirs(video_specific_dir, exist_ok=True)
    gemini_prompt_path = os.path.join(video_specific_dir, "gemini_prompt.json")
    with open(gemini_prompt_path, 'w', encoding='utf-8') as f:
        json.dump(gemini_prompt_data, f, ensure_ascii=False, indent=2)
    gemini_prompt_text = '''
次の情報は、動画の切り抜きクリップに対応したコメントデータです。各コメントは「clip_rank」と「text」というキーを持ち、clip_rankはそのコメントがどのクリップ（順位）に属しているかを表します。

各clip_rankごとに、そのクリップを代表するような「一言コメント」の候補を5つ出してください。
この一言は、実際にその場のコメント欄で誰かが言ってそうな自然なトーンの短文である必要があります。  
セリフっぽいもの、ツッコミ、感嘆、賞賛、ツイート風のリアクションなど、場面の雰囲気を一言で表すようなセリフを意識してください。

【制約】
- 各clip_rankごとに一言コメントを5つ出すこと
- コメントのtextすべてを使う必要はありません。ランダムに数個ピックアップし、それを参考にして一言を作ってください
- コメントに「::」が含まれている場合は、そのコメントは無視してください
- 出力は必ず以下のようなJSON形式で返してください（keyはclip_rank、valueは一言リスト）：

```
{
  "1": ["一言1", "一言2", "一言3", "一言4", "一言5"],
  "2": ["一言1", "一言2", "一言3", "一言4", "一言5"],
  ...
}
```

上記ルールに従って、以下のデータをもとに各clip_rankごとの一言を出力してください。
'''
    gemini_prompt_txt_path = os.path.join(video_specific_dir, "gemini_prompt.txt")
    with open(gemini_prompt_txt_path, 'w', encoding='utf-8') as f:
        f.write(gemini_prompt_text)
        f.write("\nコメントデータ:\n")
        json.dump(gemini_prompt_data, f, ensure_ascii=False, indent=2)
    return gemini_prompt_path, gemini_prompt_txt_path

def parse_and_save_gemini_output(gemini_output_path, video_id, output_dir='backend/data/gemini_comments'):
    """
    Gemini出力(json)をパースし、clip_rankごとに3件ずつ一言を保存する関数の大枠。
    保存先: backend/data/gemini_comments/{動画ID}.json
    """
    # 1. Gemini出力ファイルを開く
        # 1. Gemini出力ファイルを開く
    import re
    try:
        with open(gemini_output_path, 'r', encoding='utf-8') as f:
            gemini_data = f.read()
        # コードブロックで囲まれている場合は中身だけ抽出
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", gemini_data, re.DOTALL)
        if match:
            gemini_data = match.group(1)
    except Exception as e:
        print(f"[ERROR] Gemini出力ファイルの読み込みに失敗: {e}")
    # 2. jsonとしてパース
    try:
        data = json.loads(gemini_data)
    except Exception as e:
        print(f"[ERROR] Gemini出力のJSONパースに失敗: {e}")
        data = {}
    # 3. clip_rankごとに3件ずつ一言が入っているかバリデーション
    #    - 3件未満なら空文字で埋める
    validated = {}
    default_msg = "（一言なし）"
    num_required = 5
    if isinstance(data, dict):
        for rank, one_liners in data.items():
            # rankを整数文字列に正規化
            try:
                norm_rank = str(int(float(rank)))
            except Exception:
                norm_rank = str(rank)
            # 一言リストがlist型でなければ空リスト
            if not isinstance(one_liners, list):
                print(f"[WARN] clip_rank {rank} の値がリスト型でないため空リスト扱い")
                one_liners = []
            # 各一言がstr型であることを保証
            one_liners = [str(x) if isinstance(x, str) else default_msg for x in one_liners]
            # 5件未満ならデフォルト文言で埋める
            if len(one_liners) < num_required:
                one_liners += [default_msg] * (num_required - len(one_liners))
            elif len(one_liners) > num_required:
                print(f"[WARN] clip_rank {rank} の一言が{num_required}件を超えています。先頭{num_required}件のみ使用")
                one_liners = one_liners[:num_required]
            validated[norm_rank] = one_liners
    else:
        print("[ERROR] Gemini出力の形式が不正です (dict expected)")
        validated = {}

    # 4. 保存先ディレクトリを作成
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{video_id}.json")

    # 5. backend/data/gemini_comments/{動画ID}.json に保存
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(validated, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] Geminiコメントjsonの保存に失敗: {e}")
        return None

    # 6. 保存パスを返す
    return output_path

# Gemini CLIを実行する関数
def gemini_api_func(prompt_txt_path):
    import subprocess
    import os

    # 出力ファイルパスを決める
    output_path = prompt_txt_path.replace('.txt', '_output.json')
    try:
        with open(prompt_txt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
        # Windows PowerShell用にコマンドをリスト形式で渡す
        result = subprocess.run(
            'gemini -m gemini-2.5-flash -p',
            input=prompt,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        # 標準出力をファイルに保存
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.stdout or "")
        print("[INFO] Gemini CLI呼び出し成功")
        print("stdout:\n", result.stdout)
        print("stderr:\n", result.stderr)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Gemini CLI呼び出し失敗: {e}")
        print("stdout:\n", e.stdout)
        print("stderr:\n", e.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] Gemini CLI実行に失敗: {e}")
        return None
