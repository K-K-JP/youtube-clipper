import os
import json
from utility import sanitize_filename
from file_io import save_emoji_dict, extract_all_text_comments, extract_shortcuts_from_chat_downloader_json
from youtube_handler import download_live_chat_json

def extract_custom_emojis_from_comments(comments: list) -> dict:
    """
    コメントリストからカスタム絵文字を抽出し、辞書形式で返す。
    出力形式:
    {
        ":kuzuha_face:": {
            "emojiId": "yt:emoji123",
            "label": "Kuzuha's face",
            "url": "https://yt3.ggpht.com/abc123"
        },
        ...
    }
    """
    emoji_dict = {}
    for renderer in comments:
        runs = renderer.get("message", {}).get("runs", [])
        for run in runs:
            if "emoji" in run:
                emoji = run["emoji"]
                emoji_id = emoji.get("emojiId")
                shortcuts = emoji.get("shortcuts", [])
                thumbnails = emoji.get("image", {}).get("thumbnails", [])
                label = emoji.get("image", {}).get("accessibility", {}) \
                                 .get("accessibilityData", {}).get("label", "")
                url = thumbnails[-1]["url"] if thumbnails else ""
                for shortcut in shortcuts:
                    if shortcut not in emoji_dict:
                        emoji_dict[shortcut] = {
                            "emojiId": emoji_id,
                            "label": label,
                            "url": url
                        }
    return emoji_dict

def process_emojis_from_full_chat(video_id: str, channel_name: str):
    json_path = download_live_chat_json(video_id)
    if not json_path:
        return
    actions = []
    with open(json_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line)
                replay_actions = record.get("replayChatItemAction", {}).get("actions", [])
                actions.extend(replay_actions)
            except:
                continue
    comments = extract_all_text_comments(actions)
    emoji_dict = extract_custom_emojis_from_comments(comments)
    save_emoji_dict(emoji_dict, video_id, channel_name)

def process_emojis_if_needed(video_id: str, channel_name: str):
    chat_json_path = os.path.join("backend", "clips", "cache", f"{video_id}_comments_cache.json")
    used_shortcuts = extract_shortcuts_from_chat_downloader_json(chat_json_path)
    if not used_shortcuts:
        print("[INFO] No emoji-like shortcuts found in chat-downloader JSON.")
        return
    emoji_dict_dir = os.path.join("backend", "clips", "emoji_dict")
    all_emojis = {}
    current_channel_dict = {}
    current_channel_path = os.path.join(emoji_dict_dir, f"{sanitize_filename(channel_name)}_emoji.json")
    try:
        with open(current_channel_path, 'r', encoding='utf-8') as f:
            current_channel_dict = json.load(f)
    except:
        current_channel_dict = {}
    if os.path.exists(emoji_dict_dir):
        for filename in os.listdir(emoji_dict_dir):
            if filename.endswith('_emoji.json'):
                filepath = os.path.join(emoji_dict_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        emoji_data = json.load(f)
                        all_emojis.update(emoji_data)
                except:
                    continue
    unknown_shortcuts = used_shortcuts - set(all_emojis.keys())
    missing_in_current = used_shortcuts - set(current_channel_dict.keys())
    found_in_others = missing_in_current & set(all_emojis.keys())
    if found_in_others:
        print(f"[INFO] Found {len(found_in_others)} emojis in other dictionaries. Adding to {channel_name}'s dictionary.")
        for shortcut in found_in_others:
            current_channel_dict[shortcut] = all_emojis[shortcut]
        os.makedirs(os.path.dirname(current_channel_path), exist_ok=True)
        with open(current_channel_path, 'w', encoding='utf-8') as f:
            json.dump(current_channel_dict, f, ensure_ascii=False, indent=2)
    if not unknown_shortcuts:
        print("[INFO] All custom emojis already known. Skipping yt-dlp.")
        return
    print(f"[INFO] Detected {len(unknown_shortcuts)} unknown emojis. Running yt-dlp to update emoji dictionary.")
    process_emojis_from_full_chat(video_id, channel_name)