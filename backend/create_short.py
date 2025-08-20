import gspread
import os
import config
from utility import extract_video_id, time_to_seconds
from analyzer import create_short_video

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

        # 動画IDごとに一度だけシートを開くようキャッシュを利用
        video_sheet_cache = {}
        video_values_cache = {}
        for i, row in enumerate(all_data):
            if row.get("分析フラグ") == "TRUE" and row.get("結合フラグ") == "TRUE" and row.get("投稿フラグ") != "TRUE":
                video_url = row.get("URL")
                video_id = extract_video_id(video_url)
                print(f"ショート作成中: {video_url} ({video_id})")
                try:
                    # 動画IDごとに一度だけシート・データ取得
                    if video_id not in video_sheet_cache:
                        video_sheet = gc.open_by_key(config.GOOGLE_SHEETS_ID).worksheet(video_id)
                        video_sheet_cache[video_id] = video_sheet
                        video_values = video_sheet.get_all_values()
                        video_values_cache[video_id] = video_values
                    else:
                        video_sheet = video_sheet_cache[video_id]
                        video_values = video_values_cache[video_id]
                    if len(video_values) < 3:
                        print(f"[WARNING] {video_id} シートに十分なデータがありません")
                        continue
                    header = video_values[1]  # 2行目がヘッダー
                    # ショート・ショート作成済の列インデックス取得
                    try:
                        short_idx = header.index("ショート")
                        short_done_idx = header.index("ショート作成済")
                    except ValueError:
                        print(f"[WARNING] {video_id} シートにショート列がありません")
                        continue
                    # 3行目以降をループ
                    for data_row in video_values[2:]:
                        if len(data_row) <= max(short_idx, short_done_idx):
                            continue
                        if data_row[short_idx] == "TRUE" and data_row[short_done_idx] != "TRUE":
                            # B,C,K,O列の値取得（A=0,B=1,C=2,...,K=10,O=14）
                            clip_rank = data_row[0] if len(data_row) > 0 else None
                            start_sec = time_to_seconds(data_row[1]) if len(data_row) > 1 else None
                            end_sec = time_to_seconds(data_row[2]) if len(data_row) > 2 else None
                            channel_name = data_row[10] if len(data_row) > 10 else None
                            comment = data_row[14] if len(data_row) > 14 else None
                            create_short_video(video_id=video_id, channel_name=channel_name, start_time=start_sec, end_time=end_sec, caption_text=comment, rank=clip_rank)
                            print("ショート作成完了")
                            # ショート作成済列にTRUEをセット
                            cell_row = video_values.index(data_row) + 1  # シート上の行番号（1始まり）
                            cell_col = short_done_idx + 1  # シート上の列番号（1始まり）
                            video_sheet.update_cell(cell_row, cell_col, "TRUE")
                except Exception as e:
                    print(f"ショート作成失敗: {e}")
            else:
                print(f"未分析: {row.get('URL')}")
    except Exception as e:
        print(f"[ERROR] Spreadsheet connection failed: {e}")
        raise

if __name__ == '__main__':
    main()
