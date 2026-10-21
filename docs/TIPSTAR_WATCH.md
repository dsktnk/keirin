# TIPSTAR予想師ウォッチ（v0.5）

TIPSTARの表示している**直近10件の公開予想の回収率**を、許諾済みの範囲で手動記録して時系列比較します。
自動ログイン、スクレイピング、非公開APIへのアクセス、投票機能はありません。
[TIPSTARの指標説明](https://about.tipstar.com/news/nokkari/)と[利用規約](https://about.tipstar.com/terms-tipstar/)を確認してください。サイト内容の複製・蓄積は規約の制約があるため、運用前にMIXIからの許諾が必要になる場合があります。

## CSV形式

ヘッダー（UTF-8、BOM対応）：

```csv
tipster_id,display_name,observed_at,roi_10_pct,popularity,contribution_note,source_url
```

- `tipster_id`：**同名ユーザーと混同しない安定したID**（半角英数字、`_`、`-`、最大80文字）。実際のユーザーIDが不明な場合は自分で採番して固定する
- `display_name`：表示名。後日変更しても `tipster_id` で同一人物を追跡する
- `observed_at`：画面で値を確認した日時（例 `2026-10-21T15:00:00+09:00`）。未来時刻不可
- `roi_10_pct`：TIPSTARの「回収率」表示値をパーセントで入力（例 `125` は125%）
- `popularity`：表示された整数が分かる場合のみ入力、なければ空欄
- `contribution_note`：「貢献実績」の表示を任意のメモとして記録。集計には利用しない
- `source_url`：TIPSTARの該当プロフィール等のHTTPS URL。省略可能。**自動取得には使わない**

最初の4列だけでも登録可能。CSVに個人の認証情報を含めないでください。公開ページに出したくない氏名・メモ・URLは登録しないこと。

## さくら SSH

```sh
cd /home/dsktnk/www/keirin
/usr/local/bin/python tools/watch_tipstar.py import --file /home/dsktnk/authorized_tipstar_watch.csv
/usr/local/bin/python tools/build_static.py
```

`authorized_tipstar_watch.csv` は説明用のファイル名です。自動では作成しません。実際に用意したCSVのパスを指定してください。
閲覧先：`https://dsktnk.sakura.ne.jp/keirin/tipstar_watch.html`。
CGIを有効にしていれば `index.cgi?view=watch` でも確認可能です。

## 分析上の注意

- 観測したのは「直近10件」の**重複する移動窓**。20日間観測しても20件の独立した予想にはならない
- 「観測した回収率の差」は、その期間の実損益や勝率を示さない
- 1回観測した予想師を優秀と判定しない。3回以上の観測がある予想師を上位表示するが、統計的信頼性の保証ではない
- 公開レース単位での実績・買い目を分析するには、別途適法に取得した発走前記録と払戻確定データが必要
- 書き込みはSSH専用CLI。Webからの入力や自動巡回は提供しない
