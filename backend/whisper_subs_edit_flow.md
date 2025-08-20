# クリップ生成・動画化におけるWhisper字幕手作業編集フローまとめ

## 最終目的
クリップに乗せるWhisper字幕情報（start, end, text）を手作業で整え、最終的な動画に反映させる。

---

## 現状のフロー
1. `analyze_pending_videos.py` 実行後、生成されたシートで結合に必要なデータを選択・作成。
2. `combine_ready_clips.py` 実行でクリップ結合。

---

## 目標達成のための修正ポイント

### 1. クリップごとのWhisper字幕抽出
- `process_video` 内でクリップ候補15個を抽出。
- 各クリップを部分ダウンロード。
- `run_whisper_on_video` と `whisper_segments_to_ass_data` を使い、各クリップの字幕（start, end, text）を取得。

### 2. 字幕編集用シートの作成
- `process_video` 内で `{動画ID}_subs` という新しいシートを作成。
- シートのヘッダーは「クリップランク, start, end, text」。
- 必要に応じて字幕情報を手作業で修正。

### 3. クリップ結合時の字幕情報利用
- `combine_ready_clips.py` 実行時、選択されたクリップの字幕情報を取得。
- API呼びすぎ防止のため、字幕情報はシートから取得する。
- `combine_clips_with_overlay_and_subs` 関数内で、取得した字幕情報を `whisper_segments_to_ass_data` と `create_ass_file_whisper` でASS形式に変換。
- 変換したASS字幕をクリップに合成。

---

## 実装修正箇所まとめ
1. `process_video` の修正：
    - クリップごとにWhisper字幕抽出処理を追加。
    - `{動画ID}_subs` シートの作成・保存。
2. シート編集UI/手順の明示：
    - ユーザーが字幕情報を手作業で編集できるようにする。
3. `combine_ready_clips.py` の修正：
    - クリップ選択時に字幕情報をシートから取得。
    - `combine_clips_with_overlay_and_subs` でASS字幕合成処理を追加。

---

## 注意点
- Whisper APIの呼びすぎに注意（字幕情報は一度抽出したらシートに保存し、再利用）。
- ASS字幕合成は `whisper_segments_to_ass_data` → `create_ass_file_whisper` の順で行う。
- 既存の字幕生成・合成処理との重複や競合に注意。

---

## 参考関数
- `run_whisper_on_video`
- `whisper_segments_to_ass_data`
- `create_ass_file_whisper`
- `combine_clips_with_overlay_and_subs`

---

## 次のステップ
1. process_video内で各クリップの部分動画をダウンロードし、Whisperで字幕情報（start, end, text）を抽出するロジックを追加。
2. 字幕情報（subs_infoリスト）を直接渡して、create_subs_sheet_from_process_videoで{動画ID}_subsシートを自動生成する実装を完了。
3. subs_infoリストはクリップランク・start・end・textを持つ構造。
4. 以降はシート編集・結合処理への連携設計へ進む。
