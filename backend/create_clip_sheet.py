import gspread
import os
import config
from utility import sanitize_filename, format_time, seconds_to_hms

def create_subs_sheet_from_process_video(subs_info_list, video_id, spreadsheet=None):
    """
    process_videoで抽出した字幕情報リスト（subs_info_list）をもとに、{動画ID}_subsシートを自動生成し、
    クリップランク・start・end・textを記載する
    """
    # 1. スプレッドシート接続
    if spreadsheet is None:
        try:
            service_account_path =  os.path.join('backend', 'service_account.json')
            gc = gspread.service_account(filename=service_account_path)
            spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
        except Exception as e:
            print(f"[ERROR] Spreadsheet connection failed: {e}")
            raise

    # 2. シート名
    sheet_name = f"{video_id}_subs"
    try:
        sheet = spreadsheet.worksheet(sheet_name)
        sheet.clear()
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
    except Exception as e:
        print(f"[ERROR] Worksheet access failed: {e}")
        raise

    # 3. ヘッダー
    headers = ["clip_rank", "start", "end", "text"]
    try:
        sheet.update('A2:D2', [headers])
    except Exception as e:
        print(f"[ERROR] Header update failed: {e}")
        raise

    # 4. データ行作成
    try:
        rows = []
        for sub in subs_info_list:
            row = [sub.get("clip_rank", ""), sub.get("start", ""), sub.get("end", ""), sub.get("text", "")]
            rows.append(row)
        if rows:
            sheet.update(f"A3:D{len(rows)+2}", rows)
    except Exception as e:
        print(f"[ERROR] rows作成または書き込み失敗: {e}")
        raise

    # 字幕準備完了チェックボックスの設定
    try:
        # 1行目: A1に"字幕準備完了"、B1にチェックボックス
        sheet.update('A1:B1', [["字幕準備完了", ""]])
        # B1セルにチェックボックスを設定
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] 字幕準備完了チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] Header/checkbox update failed: {e}")
        raise

    # 動画IDシートE列: 字幕シートへのリンク
    id_sheet_name = video_id
    input_sheet = spreadsheet.worksheet(id_sheet_name)
    sheet_link = f'=HYPERLINK("#gid={sheet.id}", "{video_id}_subs")'
    input_sheet.update_acell("O1", sheet_link)
    print(f"[DEBUG] 動画IDシートに字幕シートリンク追加: {video_id}")

    # 動画IDシート: 字幕完了チェックボックスの設定
    try:
        # 1行目: P1に"字幕完了"、Q1にチェックボックス
        input_sheet.update('P1:Q1', [["字幕完了", ""]])
        # Q1セルにチェックボックスを設定
        input_sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": input_sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 16,
                        "endColumnIndex": 17
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] 字幕完了チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] Header/checkbox update failed: {e}")
        raise

    # 字幕完了チェックボックスにTRUEをセット
    input_sheet.update_acell("Q1", "TRUE")

    # C列: 動画IDシートへのリンク
    video_sheet_link = f'=HYPERLINK("#gid={input_sheet.id}", "{video_id}")'
    sheet.update_acell("C1", video_sheet_link)
    print(f"[DEBUG] 字幕シートに動画シートリンク追加: {video_id}")

    print(f"✓ {sheet_name} シートを自動生成・初期化しました（Whisper字幕情報）")

    # D列（text列）に条件付き書式を追加
    try:
        # D列（3行目以降）
        start_row = 2  # 0-indexed, 3行目
        end_row = start_row + max(len(subs_info_list), 1)
        d_col = 3  # D列（0-indexed）
        rules = []
        # 1. 23文字以上かつ+が含まれていない場合は淡い赤色
        rules.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet.id,
                        "startRowIndex": start_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": d_col,
                        "endColumnIndex": d_col+1
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": "=AND(LEN(D3)>=23, ISERROR(FIND(\"+\", D3)))"}]
                        },
                        "format": {"backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}}
                    }
                },
                "index": 0
            }
        })
        # 2. OR式
        rules.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet.id,
                        "startRowIndex": start_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": d_col,
                        "endColumnIndex": d_col+1
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": "=OR(LEN(REGEXEXTRACT(D3, \"^[^+]+\"))>22, LEN(REGEXEXTRACT(D3, \"[^+]+$\"))>22)"}]
                        },
                        "format": {"backgroundColor": {"red": 0.8, "green": 1, "blue": 0.8}}
                    }
                },
                "index": 0
            }
        })
        # ルールを一括追加
        sheet.spreadsheet.batch_update({"requests": rules})
        print(f"[DEBUG] D列条件付き書式追加完了")
    except Exception as e:
        print(f"[ERROR] D列条件付き書式追加失敗: {e}")
    return sheet

def create_clip_sheet_from_process_video(process_video_result, video_id, spreadsheet=None):
    """
    process_videoの出力（clips等）をもとに、{動画ID}シートを自動生成し、必要な列を入力・不要な列は非表示にする
    一言候補列はプルダウン、決定一言列は候補のいずれかを選択または手入力可
    """
    # 1. スプレッドシート接続
    if spreadsheet is None:
        try:
            service_account_path =  os.path.join('backend', 'service_account.json')
            print(f"[DEBUG] service_account_path: {service_account_path}")
            gc = gspread.service_account(filename=service_account_path)
            spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
            print(f"[DEBUG] Opened spreadsheet: {config.GOOGLE_SHEETS_ID}")
        except Exception as e:
            print(f"[ERROR] Spreadsheet connection failed: {e}")
            raise

    # 2. シート名
    sheet_name = video_id
    try:
        print(f"[DEBUG] Try to get worksheet: {sheet_name}")
        sheet = spreadsheet.worksheet(sheet_name)
        sheet.clear()
        print(f"[DEBUG] Worksheet {sheet_name} found and cleared.")
    except gspread.WorksheetNotFound:
        print(f"[DEBUG] Worksheet {sheet_name} not found. Creating new.")
        sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
    except Exception as e:
        print(f"[ERROR] Worksheet access failed: {e}")
        raise

    # 3. シート上部に"処理準備"とチェックボックスを追加し、2行目に既存ヘッダーを配置
    headers = [
        "クリップNo",           # 0
        "開始秒",               # 1
        "終了秒",               # 2
        "main_label",           # 3
        "labels",               # 4
        "window_score",         # 5
        "max_scores_laugh",     # 6
        "max_scores_healing",   # 7
        "max_scores_chaos",     # 8
        "group_id",             # 9
        "channel",              # 10
        "video_id",             # 11
        "クリップ確認URL",      # 12
        "一言候補",             # 13
        "決定一言",             # 14
        "結合チェック",         # 15
        "結合順",               # 16
        "ショート",             # 17
        "ショート作成済"        # 18
    ]
    try:
        # 1行目: A1に"処理準備"、B1にチェックボックス
        sheet.update('A1:B1', [["処理準備", ""]])
        # 2行目: ヘッダー
        sheet.update(f"A2:{chr(65+len(headers)-1)}2", [headers])
        # B1セルにチェックボックスを設定
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] ヘッダー・処理準備チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] Header/checkbox update failed: {e}")
        raise

    try:
        # 1行目: M1に"字幕準備"、N1にチェックボックス
        sheet.update('M1:N1', [["字幕準備", ""]])
        # N1セル（チェックボックス用）だけにデータバリデーションを設定
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 13,
                        "endColumnIndex": 14
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] 字幕準備チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] Header/checkbox update failed: {e}")
        raise

    # 4. データ行作成
    try:
        clips = process_video_result.get("clips", [])
        gemini_comments = process_video_result.get("gemini_comments", {})
        group_id = process_video_result.get("group_id", "")
        channel = process_video_result.get("channel", "")
        video_id_val = process_video_result.get("video_id", video_id)
        print(f"[DEBUG] clips: {len(clips)}, gemini_comments: {type(gemini_comments)}, group_id: {group_id}, channel: {channel}, video_id_val: {video_id_val}")
    except Exception as e:
        print(f"[ERROR] process_video_result parse failed: {e}")
        raise

    rows = []
    try:
        for idx, clip in enumerate(clips, 1):
            # start_sec, end_secはprocess_videoの出力には存在せず、正しくはstart, end（秒数, float/int）を使う必要がある
            start_sec_raw = clip.get("start", "")
            start_sec=format_time(start_sec_raw)
            end_sec_raw = clip.get("end", "")
            end_sec=format_time(end_sec_raw)
            main_label = clip.get("main_label", "")
            labels = ",".join(clip.get("labels", [])) if isinstance(clip.get("labels", []), list) else clip.get("labels", "")
            window_score = clip.get("window_score", "")
            max_scores = clip.get("max_scores", {})
            max_scores_laugh = max_scores.get("laugh", "")
            max_scores_healing = max_scores.get("healing", "")
            max_scores_chaos = max_scores.get("chaos", "")
            group_id_val = clip.get("group_id", group_id)
            channel_val = clip.get("channel", channel)
            video_id_clip = clip.get("video_id", video_id_val)
            # クリップ確認用YouTube URL
            base_url = process_video_result.get("video_url", "")
            if base_url:
                confirm_url = f"{base_url}&t={int(start_sec_raw)}s" if start_sec_raw else base_url
            else:
                confirm_url = ""
            # 一言候補
            rank = str(clip.get("rank", idx))
            gemini_list = gemini_comments.get(rank, []) if isinstance(gemini_comments, dict) else []
            candidates = [c for c in gemini_list if c]
            candidate_str = ", ".join(candidates)
            # 決定一言・結合チェック・結合順・備考は空欄
            row = [
                idx, start_sec, end_sec, main_label, labels, window_score,
                max_scores_laugh, max_scores_healing, max_scores_chaos,
                group_id_val, channel_val, video_id_clip, confirm_url,
                "", "", False, "", False, False
            ]
            rows.append((row, candidates))
        print(f"[DEBUG] rows作成完了: {len(rows)}件")
        if rows:
            # データは3行目から書き込む
            sheet.update(f"A3:{chr(65+len(headers)-1)}{len(rows)+2}", [r[0] for r in rows])
            print(f"[DEBUG] rowsをシートに書き込み完了")
    except Exception as e:
        print(f"[ERROR] rows作成または書き込み失敗: {e}")
        raise

    # 5. データ検証（結合順プルダウン、結合チェックボックス、一言候補プルダウン、ショート/ショート作成済チェックボックス）
    # データは3行目から始まるので、バリデーション範囲も+1する
    # 結合順: 1～クリップ数のプルダウン
    try:
        rule = {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": str(i)} for i in range(1, len(rows)+1)]},
            "showCustomUi": True,
            "strict": True
        }
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 2,
                        "endRowIndex": len(rows)+2,
                        "startColumnIndex": 16,
                        "endColumnIndex": 17
                    },
                    "rule": rule
                }
            }]
        })
        print(f"[DEBUG] 結合順プルダウン設定完了")
    except Exception as e:
        print(f"[ERROR] 結合順プルダウン設定失敗: {e}")
    # 結合チェック: チェックボックス
    try:
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 2,
                        "endRowIndex": len(rows)+2,
                        "startColumnIndex": 15,
                        "endColumnIndex": 16
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] 結合チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] 結合チェックボックス設定失敗: {e}")
    # ショート: チェックボックス
    try:
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 2,
                        "endRowIndex": len(rows)+2,
                        "startColumnIndex": 17,
                        "endColumnIndex": 18
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] ショートチェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] ショートチェックボックス設定失敗: {e}")
    # ショート作成済: チェックボックス
    try:
        sheet.spreadsheet.batch_update({
            "requests": [{
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": 2,
                        "endRowIndex": len(rows)+2,
                        "startColumnIndex": 18,
                        "endColumnIndex": 19
                    },
                    "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                }
            }]
        })
        print(f"[DEBUG] ショート作成済チェックボックス設定完了")
    except Exception as e:
        print(f"[ERROR] ショート作成済チェックボックス設定失敗: {e}")
    # 一言候補: その行の候補のみプルダウン
    try:
        for row_idx, (row, candidates) in enumerate(rows, start=3):
            if candidates:
                rule = {
                    "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": c} for c in candidates]},
                    "showCustomUi": True,
                    "strict": False
                }
                sheet.spreadsheet.batch_update({
                    "requests": [{
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet.id,
                                "startRowIndex": row_idx-1,
                                "endRowIndex": row_idx,
                                "startColumnIndex": 13,
                                "endColumnIndex": 14
                            },
                            "rule": rule
                        }
                    }]
                })
        print(f"[DEBUG] 一言候補プルダウン設定完了")
    except Exception as e:
        print(f"[ERROR] 一言候補プルダウン設定失敗: {e}")

    # 6. 非表示にする列（例: main_label, labels, window_score, max_scores_* など）
    try:
        hidden_columns = [3,4,5,6,7,8,9,10,11]  # 0-indexed: main_label, labels, window_score, max_scores_*
        requests = []
        for col in hidden_columns:
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": col,
                        "endIndex": col+1
                    },
                    "properties": {"hiddenByUser": True},
                    "fields": "hiddenByUser"
                }
            })
        if requests:
            sheet.spreadsheet.batch_update({"requests": requests})
        print(f"[DEBUG] 非表示列設定完了")
    except Exception as e:
        print(f"[ERROR] 非表示列設定失敗: {e}")

    print(f"✓ {sheet_name} シートを自動生成・初期化しました（候補プルダウン＆決定一言式対応）")

    # 7. 入力用シートの更新
    try:
        input_sheet = spreadsheet.worksheet("入力用")
        input_values = input_sheet.get_all_values()
        # ヘッダー取得
        header = input_values[0] if input_values else []
        url_col = 0  # A列
        groupid_col = 1  # B列
        sheet_col = 2  # C列
        analysis_flag_col = 3  # D列
        combine_flag_col = 4  # E列
        upload_flag_col = 5  # F列
        upload_complete_col = 6  # G列
        channel_name_col = 7  # H列
        video_title_col = 8  # I列
        upload_date_col = 9  # J列
        # 動画URL取得
        video_url = process_video_result.get("video_url", "")
        group_id = process_video_result.get("group_id", "")
        # 既存URL一覧
        url_list = [row[url_col] for row in input_values[1:] if len(row) > url_col]
        # 既存に無ければ追加
        if video_url not in url_list:
            new_row_idx = len(input_values) + 1  # 1-indexed
            input_sheet.update(f"A{new_row_idx}:B{new_row_idx}", [[video_url, group_id]])
            # D列: 分析フラグにチェックボックス+ON
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": new_row_idx-1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": analysis_flag_col,
                            "endColumnIndex": analysis_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # 初期値 TRUE を設定（チェックON）
            cell = input_sheet.cell(row_idx, analysis_flag_col + 1)
            cell.value = "TRUE"
            input_sheet.update_cells([cell])
            # E列: 結合フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": new_row_idx-1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": combine_flag_col,
                            "endColumnIndex": combine_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # F列: 投稿フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": new_row_idx-1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": upload_flag_col,
                            "endColumnIndex": upload_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # G列: 投稿完了フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": new_row_idx-1,
                            "endRowIndex": new_row_idx,
                            "startColumnIndex": upload_complete_col,
                            "endColumnIndex": upload_complete_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # C列: シートへのリンク
            sheet_link = f'=HYPERLINK("#gid={sheet.id}", "{video_id}")'
            input_sheet.update_acell(f"C{new_row_idx}", sheet_link)
            print(f"[DEBUG] 入力用シートに新規行追加: {video_url}")
            # H列: チャンネル名
            channel_name = sanitize_filename(channel)
            input_sheet.update_acell(f"H{new_row_idx}", channel_name)
            # I列: 動画タイトル
            video_title = process_video_result.get("title", "")
            input_sheet.update_acell(f"I{new_row_idx}", video_title)
        else:
            # 既存の場合は行番号を特定
            row_idx = url_list.index(video_url) + 2  # 1-indexed, +1 for header
            # 分析フラグをON
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": row_idx-1,
                            "endRowIndex": row_idx,
                            "startColumnIndex": analysis_flag_col,
                            "endColumnIndex": analysis_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # 初期値 TRUE を設定（チェックON）
            input_sheet.update_acell(f"D{row_idx}", "TRUE") 
            # E列: 結合フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": row_idx-1,
                            "endRowIndex": row_idx,
                            "startColumnIndex": combine_flag_col,
                            "endColumnIndex": combine_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # F列: 投稿フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": row_idx-1,
                            "endRowIndex": row_idx,
                            "startColumnIndex": upload_flag_col,
                            "endColumnIndex": upload_flag_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # G列: 投稿完了フラグにチェックボックス
            input_sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": input_sheet.id,
                            "startRowIndex": row_idx-1,
                            "endRowIndex": row_idx,
                            "startColumnIndex": upload_complete_col,
                            "endColumnIndex": upload_complete_col+1
                        },
                        "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}
                    }
                }]
            })
            # C列: シートへのリンクを更新
            sheet_link = f'=HYPERLINK("#gid={sheet.id}", "{video_id}")'
            input_sheet.update_acell(f"C{row_idx}", sheet_link)
            print(f"[DEBUG] 入力用シートの既存行を更新: {video_url}")
            # H列: チャンネル名
            channel_name = sanitize_filename(channel)
            input_sheet.update_acell(f"H{row_idx}", channel_name)
            # I列: 動画タイトル
            video_title = process_video_result.get("title", "")
            input_sheet.update_acell(f"I{row_idx}", video_title)
    except Exception as e:
        print(f"[ERROR] 入力用シートの更新失敗: {e}")
    return sheet

def set_combine_flag_true(video_url):
    """
    入力用シートのA列(URL)でvideo_urlを検索し、該当行のE列(結合フラグ)のチェックボックスをTRUEにする
    """
    try:
        import gspread
        import config
        # スプレッドシート接続
        service_account_path = os.path.join('backend', 'service_account.json')
        gc = gspread.service_account(filename=service_account_path)
        spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
        input_sheet = spreadsheet.worksheet("入力用")
        input_values = input_sheet.get_all_values()
        url_col = 0  # A列
        combine_flag_col = 4  # E列 (0-indexed)
        # URL列から該当行を検索
        for idx, row in enumerate(input_values[1:], start=2):  # 1-indexed, +1 for header
            if len(row) > url_col and row[url_col] == video_url:
                # E列のチェックボックスをTRUEに
                input_sheet.update_acell(f"E{idx}", "TRUE")
                print(f"[DEBUG] 結合フラグをON: 行{idx} ({video_url})")
                return True
        print(f"[WARN] 入力用シートに該当URLが見つかりません: {video_url}")
        return False
    except Exception as e:
        print(f"[ERROR] set_combine_flag_true失敗: {e}")
        return False

# def set_short_flag_true(video_id):
#     """
#     入力用シートのA列(URL)でvideo_idを検索し、該当行のH列(ショートフラグ)のチェックボックスをTRUEにする
#     """
#     try:
#         import gspread
#         import config
#         # スプレッドシート接続
#         service_account_path = os.path.join('backend', 'service_account.json')
#         gc = gspread.service_account(filename=service_account_path)
#         spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_ID)
#         input_sheet = spreadsheet.worksheet(video_id)
#         input_values = input_sheet.get_all_values()
#         short_flag_col = 18  # S列 (0-indexed)
#         # URL列から該当行を検索
#         for idx, row in enumerate(input_values[1:], start=2):  # 1-indexed, +1 for header
#             if len(row) > url_col and row[url_col] == video_url:
#                 # S列のチェックボックスをTRUEに
#                 input_sheet.update_acell(f"S{idx}", "TRUE")
#                 print(f"[DEBUG] ショートフラグをON: 行{idx} ({video_url})")
#                 return True
#         print(f"[WARN] 入力用シートに該当URLが見つかりません: {video_url}")
#         return False
#     except Exception as e:
#         print(f"[ERROR] set_short_flag_true失敗: {e}")
#         return False