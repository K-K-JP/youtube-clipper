import gspread
import os
import config
from analyzer import generate_subs
from utility import extract_video_id, time_to_seconds

def main():
    # スプレッドシート認証設定
    try:
        service_account_path =  os.path.join('backend', 'service_account.json')
        print(f"[DEBUG] service_account_path: {service_account_path}")
        gc = gspread.service_account(filename=service_account_path)
        spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
        print(f"[DEBUG] Opened spreadsheet: {config.GOOGLE_SHEETS_ID}")
        SHEET_NAME = "入力用"

        # スプレッドシート取得
        sheet = spreadsheet.worksheet(SHEET_NAME)
        all_data = sheet.get_all_records()

        for i, row in enumerate(all_data):
            if row.get("分析フラグ") == "TRUE" and row.get("結合フラグ") != "TRUE":
                video_url = row.get("URL")
                video_id = extract_video_id(video_url)
                try:
                    # 該当動画のシートを開く
                    video_sheet = gc.open_by_key(config.GOOGLE_SHEETS_ID).worksheet(video_id)
                    ready_flag = video_sheet.acell("N1").value  # N1に字幕準備フラグ
                    already_flag = video_sheet.acell("Q1").value  # Q1に字幕完了フラグ
                    if ready_flag == "TRUE" and already_flag != "TRUE":
                        print(f"字幕作成中: {video_id} ({video_url})")
                        # クリップ情報取得（3行目以降）
                        clip_values = video_sheet.get_all_values()[2:]  # 3行目以降
                        clips = []
                        # group_id（J3セル値）はループ外で1回だけ取得
                        group_id = video_sheet.acell("J3").value if video_sheet else ""
                        # 動画メタデータも1回だけ取得
                        from youtube_handler import get_video_metadata
                        metadata = get_video_metadata(video_url)
                        channel_name = metadata.get('channel', '') or ''
                        print(f"[DEBUG] 動画メタデータ: {channel_name}")
                        # gemini_comments_jsonも1回だけ取得
                        gemini_comments_path = os.path.join('backend', 'data', 'gemini_comments', f'{video_id}.json')
                        import json
                        if os.path.exists(gemini_comments_path):
                            with open(gemini_comments_path, 'r', encoding='utf-8') as f:
                                gemini_comments_json = json.load(f)
                        else:
                            gemini_comments_json = {}
                        for clip_row in clip_values:
                            try:
                                combine_checked = str(clip_row[15]).upper() == "TRUE"
                                if combine_checked :
                                    rank_val = int(clip_row[0])
                                    clips.append({
                                        "start_sec": time_to_seconds(clip_row[1]),
                                        "end_sec": time_to_seconds(clip_row[2]),
                                        "rank": rank_val,
                                        "main_label": clip_row[3],
                                        "comment": clip_row[14],
                                        "group_id": group_id,
                                        "channel": channel_name,
                                        "video_id": video_id,
                                        "gemini_comments": gemini_comments_json.get(str(rank_val), []),
                                        "laugh_score": float(clip_row[6]) if clip_row[6] else None,
                                        "healing_score": float(clip_row[7]) if clip_row[7] else None,
                                        "chaos_score": float(clip_row[8]) if clip_row[8] else None,
                                        "window_score": float(clip_row[5]) if clip_row[5] else None
                                    })
                            except Exception as e:
                                print(f"[WARN] クリップ行解析失敗: {e}")
                        # 結合順でソート
                        print(f"結合中: {video_id} クリップ数: {len(clips)}")
                        generate_subs(video_url=video_url, video_id=video_id, combine_order=clips)
                        print("結合完了")
                    else:
                        print(f"字幕準備フラグがOFF: {video_id} (N1: {ready_flag})")
                except Exception as e:
                    print(f"結合失敗: {e}")
            else:
                print(f"分析フラグ: {row.get('分析フラグ')} 結合フラグ: {row.get('結合フラグ')}")

    except Exception as e:
        print(f"[ERROR] Spreadsheet connection failed: {e}")
        raise
if __name__ == '__main__':
    main()