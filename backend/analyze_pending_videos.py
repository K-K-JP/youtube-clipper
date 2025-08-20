import gspread
import os
import config
from analyzer import process_video

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
            if not row.get("分析フラグ") == "TRUE":
                video_url = row.get("URL")
                group_id = row.get("グループID")

                print(f"分析中: {video_url} ({group_id})")
                try:
                    process_video(video_url=video_url, group_id=group_id,duration_minutes=0)
                    print("分析完了")
                except Exception as e:
                    print(f"分析失敗: {e}")
            else:
                print(f"既に分析済み: {row.get('URL')}")
    except Exception as e:
        print(f"[ERROR] Spreadsheet connection failed: {e}")
        raise

if __name__ == '__main__':
    main()
