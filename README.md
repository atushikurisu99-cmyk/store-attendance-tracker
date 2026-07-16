# 店舗出勤状況トラッカー

シティヘブンネット掲載店舗の「出勤人数」「新人登録数」だけを日次で取得し、
GitHub Pages上で一覧・グラフ表示するツールです。キャスト個人の名前・年齢等は保持しません。

## 含まれているもの(今回のスコープ)

- `scraper/scrape.py` … 店舗ごとに出勤人数・直近7日の新人数を取得し、`data/` にJSON蓄積
- `.github/workflows/scrape.yml` … 1日3回(10時/17時/23時、各回0〜5分のランダム遅延)自動実行
- `config/stores.json` … 監視対象の店舗一覧(現在5店舗: elegance, hiroshima_hyoban, kagayaki, lovemachine, rush)
- `docs/index.html` … GitHub Pages公開用フロント(一覧+店舗タップで曜日別×直近4週間の重ね折れ線グラフ、横固定レイアウト)

## 含まれていないもの(次のフェーズで着手予定)

- 検索窓からの店舗追加機能
- 一覧画面でのチェックボックス削除機能
- 広島市エリア全店舗パトロール(在籍人数・新店舗検知・新人急増通知の統合ロジック)

## 今回追加した内容

- **文字サイズ**: 全体的に大きめのフォントサイズに調整(基準18px、店舗名17px、出勤人数24px)
- **前日比**: 23時実行時点の記録同士で比較する設計(`scraper/scrape.py`は現状1日1回分に上書きする作りなので、23時実行のタイミングでのみhistoryへ正式記録するよう運用するのがおすすめ)
- **通知欄**: 新人急増(週3人以上)をLINE風に画面右上へ積み上げ表示。新店舗追加通知は全店舗パトロール機能の実装後に同じ仕組みへ接続する想定(現状は未接続)
- **欠損データ**: グラフは該当日を単純にスキップする実装(`spanGaps: true`)
- **PWA化**: `docs/manifest.json` + `docs/service-worker.js` を追加。縦持ちの端末では横向きへの回転を促すメッセージを表示する(CSSでの強制回転はブラウザ間で挙動が不安定なため不採用)。iOSは「ホーム画面に追加」経由でのみ`manifest.json`の`orientation: landscape`が効く点に注意
- **アイコン**: `manifest.json`の`icons`は空のままなので、実際にホーム画面へ追加する場合は192x192等のアイコン画像を用意して追記する必要あり

## セットアップ手順

1. このZIPの中身を新規リポジトリ(Private推奨)にそのままpush
2. リポジトリの Settings → Pages で、公開元を `/docs` フォルダに設定
3. Settings → Actions → General で、Workflow permissions を
   「Read and write permissions」に変更(Actionsが `data/` をコミットするため)
4. Actions タブから `Scrape store attendance` を手動実行(`workflow_dispatch`)して疎通確認
   - 最初の1回は `elegance` 1店舗だけ動かして、正しく人数が取れるか確認するのがおすすめ
5. 問題なければ、あとは自動スケジュールに任せる

## 疎通確認で見るべきポイント

`scraper/scrape.py` の抽出ロジック(`count_today_attendance` / `count_recent_newface`)は
トップページのHTML構造を元にした暫定版です。実際に `/attend/` ページへアクセスした際の
レスポンスを見て、以下を確認・調整してください。

- 403やタイムアウトで弾かれていないか(Actionsのログで確認)
- 取得できた人数が、実際にサイトを見た人数と一致するか
- 「本日」列だけを正しく拾えているか(曜日タブ切り替えのDOM構造次第で調整が必要)

## データの保存形式

- `data/history.json` … `{ slug: [ {date, attendance, newface}, ... ] }` の形で日次蓄積
- `data/latest.json` … 直近実行時点のスナップショット(一覧画面が読む)

## 負荷対策として組み込んでいること

- 店舗の処理順序を毎回シャッフル
- 店舗ごとのリクエスト間に1〜2秒のランダムインターバル
- ブラウザ相当のUser-Agent
- 403/429時の簡易バックオフ・リトライ
- Actions実行開始時刻に0〜5分のランダム遅延
