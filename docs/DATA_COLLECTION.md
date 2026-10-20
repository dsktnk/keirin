# KEIRIN LAB v0.4: 実レース履歴CSV取得

## 目的と範囲

外部から取得した競輪履歴を **予想テーブルとは別の** `feed_races` / `feed_riders` / `feed_runs` へ格納します。予想に必要な発走前の特徴量が存在しないため、**新規予測や回収率を捏造しません**。実際の選手名や成績を画面に転載する機能も初期版では無効にし、取得件数と日付のみ表示します。

* 対応形式：`Kenseimk/keirin-data` の月別CSVと同じカラム構成
* 入力方法：手動CSV、または**取得・利用許諾を確認済み**のHTTPS CSV URL
* URL直接取得を許すホストは `raw.githubusercontent.com` のみ。URLはCLIの引数として運営者が指定します。
* 同一ファイル：SHA-256で検出、再取得しても二重計上しない
* 更新内容：同一source/race_id/banumを上書きし履歴ログを残す（値の変遷までは保存しない）
* 公開CGI経由の取り込みは不可。cron登録は行わない。

## 取得例（さくら SSH）

```sh
cd /home/dsktnk/www/keirin
/usr/local/bin/python tools/collect.py --source my_licensed_data --file /home/dsktnk/keirin-data/2026_09_keirin.csv
/usr/local/bin/python tools/build_static.py
```

データファイルは `www` の外へ置くのを推奨。プログラム本体は指定の `www/keirin` 内のまま動作します。

HTTPSから明示的に取得する場合：

```sh
/usr/local/bin/python tools/collect.py --source licensed_csv --url 'https://raw.githubusercontent.com/OWNER/REPO/main/path/to/month.csv'
/usr/local/bin/python tools/build_static.py
```

このURLは形式例であり、利用可能な公開データAPIや再利用権を保証するものではありません。URL取得実行前に、データ提供元の利用条件を確認してください。

画面: https://dsktnk.sakura.ne.jp/keirin/feed.html （CGIの場合は `index.cgi?view=feed`）。

## 実データの現状

この形式の出走履歴には、レースの正式な発走時刻、発走前の勝率・連対率、公開オッズの取得時刻がありません。履歴収集データをいきなり `races` や `forecasts` にコピーすると、過去の成績を利用した見せかけの精度を生むため、禁止しています。次の版では **発走前スナップショットを取得できる正式なデータ供給元** と連動させます。

## 権利・利用条件

KEIRIN.JPはサイトポリシーでコンテンツの複製・転用を制限しています。第三者がGitHubで公開しているファイルも自由な再配布許諾を意味しません。**自動巡回・第三者データ転載の権利確認を済ませるまで、このスクリプトを定期実行しないでください。**
