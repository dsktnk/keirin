# KEIRIN LAB v0.9 — GitHub main正本

**GitHub の main を唯一の正本**として利用します。静的HTMLはCGIなしでも動き、デモ用の架空データが残っています。

## さくらへの最短設置

1. ZIPをMac上で展開する。
2. 中身のファイルとフォルダを **`/home/dsktnk/www/keirin/` の直下** に上書きアップロードする。
   - `index.html` が **`/home/dsktnk/www/keirin/index.html`** になること。
   - `keirin_lab_upload_v0_5/` という名前のフォルダをもう一つ作って入れないこと。
3. **https://dsktnk.sakura.ne.jp/keirin/** を開く。ログイン操作もSSHも不要。

表示データは架空です。実際の競輪データはCSV取込操作後に取得状況画面へ反映されます。TIPSTARのデータは取得していません。
今回の配布ZIPはデータベースを含まず、既存の `data/keirin_lab.sqlite3` を上書きしません。新規設置でCGIを使用する場合だけ `/usr/local/bin/python tools/cli.py seed-demo` でデモDBを生成してください。

## 任意：CGI版を使う

アップロードした `index.cgi` の権限を、SSHやFTPの属性変更で `755` にする（ZIPからサーバー上で `unzip` した場合は保持されることがあります）。

    chmod 755 /home/dsktnk/www/keirin/index.cgi

その後 https://dsktnk.sakura.ne.jp/keirin/index.cgi にアクセス。CGI版は `data/keirin_lab.sqlite3` を都度参照します。

さくらの推奨CGI設定は `.cgi` / `755` または `705` / Python `/usr/local/bin/python`。フォルダ配置だけで動く静的HTML版に権限変更は不要です。

## データ更新

CSVインポートや snapshot を行った後、HTMLの内容も更新したいならSSHで次を実行：

    cd /home/dsktnk/www/keirin
    /usr/local/bin/python tools/build_static.py

再生成しなくてもCGI版には最新のSQLiteデータが反映されます。

    /usr/local/bin/python tools/cli.py report

## アプリの内容

- `index.html`：デモレース一覧・統合ダッシュボード
- `race_DEMO_....html`：各レースの2車単予測・支持率
- `tipsters.html` / `tipsters_10.html` / `tipsters_30.html`：予想師比較
- `backtest.html`：架空レースのバックテスト
- `index.cgi`：読み取り専用CGI版
- `src/`：Pythonコード
- `data/`：架空SQLiteデータ（必要最小限の .htaccess によるアクセス制限あり）
- `tools/`：CLI / 静的ページ再生成

公開サイトには**分析デモのみ**置いてください。個人情報・APIキー・認証情報は `www` 以下に保存しないでください。

学習済みAIモデル・実データ自動取得・TIPSTARログイン・投票処理は未実装です。

## v0.4：実レース履歴の取得（オプション）

ユーザーが許諾を確認したCSVを手動操作で取得し、独立した履歴テーブルに保存できます。GitHub等のURLからの取得も可能ですが、自動スクレイピング・実オッズ/予想師取得は未実装。**詳しい操作とCSV形式は `docs/DATA_COLLECTION.md`**。

    cd /home/dsktnk/www/keirin
    /usr/local/bin/python tools/collect.py --source allowed_source --file /home/dsktnk/history.csv
    /usr/local/bin/python tools/build_static.py

閲覧：`feed.html` / `index.cgi?view=feed`。データソースの公開許諾未確認のため、表示は件数・日付の集計のみ。既存の架空デモレースと履歴取得データは混在させません。


## v0.5：TIPSTAR予想師ウォッチ

TIPSTARとはログイン・自動取得していません。許諾済みの観測値を手動CSVで保存し、直近10公開予想の回収率の推移を比較します。

    /usr/local/bin/python tools/watch_tipstar.py import --file /実在する/観測.csv
    /usr/local/bin/python tools/build_static.py

閲覧ページ： `tipstar_watch.html` 。詳しくは `docs/TIPSTAR_WATCH.md` を参照してください。


## 公開TIPSTARページの単発取得診断（実験）

v0.5には閲覧可能な公開ページがさくらから取得できるかを調べる安全側の診断ツールを追加しました。**自動収集や予想師別データ保存ではありません**。取得先の事前選定と規約の確認が必要です。

```sh
cd /home/dsktnk/www/keirin
/usr/local/bin/python tools/probe_tipstar.py --url 'https://tipstar.com/user/keirin/2026-10-16_12_05/race_predictors'
```

一度の実行で1ページ、次の実行まで120秒以上。HTTPアクセス不可の場合は失敗します。CGI画面からは実行されず、cronも未設定です。詳細は `docs/TIPSTAR_PROBE.md` を参照してください。


## v0.6：MIRAの予測精度を育てる土台

`research.html`（静的版）、`index.cgi?view=research`（CGI版）に研究スコアカードを追加。

- 実戦とデモの予測を混ぜずに検証します。
- 発走前に固定した2車単の確率分布と確定着順を照合し、1点的中率、上位3点率、対数損失、Brierスコアを計算します。
- 払戻データが揃ったレースについてのみ仮想100円1点の回収率を表示します。
- 発走後の予測、未来の出走情報、不完全な分布は検証から除外します。
- まだデータ取得やMIRAの学習は実装されておらず、実戦評価0件は正常です。

データを取り込んだら `/usr/local/bin/python tools/build_static.py` でHTMLを更新できます。詳細は `docs/MIRA_RESEARCH.md`。

テスト: `python -m unittest discover -s tests -v`（GitHub Actionsにもテストを追加）。


## v0.7：実レース → MIRA予想 → 結果照合

実出走表をJSONから一件ずつ登録し、発走前に比較モデルとMIRAの判断根拠・買い目を固定。結果確定後に的中率・仮想回収率を研究画面へ表示する運用です。**データ自動取得・AI API接続・投票は未実装**。`tools/real_race.py` が操作CLI、`docs/MIRA_V07.md` が入力JSON形式・運用ガイドです。既存SQLiteは削除・上書きしません。

1. `python3 tools/real_race.py register --file ./local/real_racecard.json`
2. `python3 tools/real_race.py baseline --race YOUR_RACE_ID`
3. `python3 tools/real_race.py predict --file ./local/mira_prediction.json`
4. 結果確定後 `python3 tools/real_race.py settle --file ./local/real_result.json`
5. `python3 tools/build_static.py` → `research.html`

実レースの検証可能なデータが未入力なら評価0件が正しい状態です。GitHubの`main`を正本として運用してください。


## v0.8：日次実出走表の自動取り込み基盤

**対象:** 日次JSONの出走表から発走前の実レースだけを最大3件登録し、既存の比較用モデル確率を固定。登録できた場合は `research.html` も再生成。

**注意:** 外部リポジトリの公開データについて再利用ライセンスを確認できていないため、データの蓄積を自動的に有効にはしていません。権利と利用条件が確認できてから、次を実行してください。

```bash
/usr/local/bin/python tools/ingest_daily.py --fetch-today --source-rights-confirmed
```

サイトへのネットワークアクセスは1実行につき1日次JSONファイル、1時間以上間隔を設けます。利用条件を確認せずにcronへ登録しないでください。詳しくは `docs/MIRA_V08.md`。\n\nローカルJSONを保存する場合は出所の`--source-url`も必須（dry-run除く）。

現在は実レース出走表の取得・比較モデルの凍結まで。**MIRAの独自予想、2車単の払戻・確定結果の自動取り込みは未接続**です。GitHub mainのコード更新とSakuraでの自動実行設定は別の作業です。


## v0.9: 結果・2車単払戻との照合

結果JSONを厳格に照合して未確定レースを除外。tools/settle_daily.py を追加。初期状態は書き込みを行わない診断モードです。取得元の権利は未確認なのでcron・収集は有効化していません。操作手順は docs/MIRA_V09.md に記載。
