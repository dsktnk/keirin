# KEIRIN LAB v1.0 — MIRA競輪予測研究

**正本は [GitHubのmain](https://github.com/dsktnk/keirin)。** ZIPは配布しません。Python 3.8 / SQLite / CGI / 静的HTMLの軽量構成です。

## 目的

MIRAが競輪の予想精度を改善できるか、**発走前の予想を凍結 → 確定結果と照合 → 同一レースで比較**して検証する。的中率・確率の較正・回収率は別の指標として扱い、過去結果を予測へ混入させない。

## 更新方法

クローン済みのリポジトリで実行してください。

~~~sh
git pull origin main
python3 -m unittest discover -s tests -v
~~~

さくらの `/home/dsktnk/www/keirin/` 自体がクローンなら、そのディレクトリで `git pull origin main`。Macだけでクローンしている場合は、Macで更新してからサーバーへ同期。SQLiteの実データ `data/keirin_lab.sqlite3` はGitに含めず、削除・上書きしません。

## 画面

- `research.html`：MIRA予測・モデル比較の静的HTML
- `index.cgi?view=research`：SQLiteを直接参照する研究画面（読み取り専用）
- `index.html`：ダッシュボード（デモレースを含む）
- `tipsters.html` / `tipstar_watch.html`：過去バージョンの予想師・TIPSTAR研究
- `backtest.html`：既存の比較バックテスト

実データ更新後の静的HTML生成:

~~~sh
/usr/local/bin/python tools/build_static.py
~~~

CGIを使う場合 `chmod 755 index.cgi`。SakuraのPython: `/usr/local/bin/python`。

## 実戦研究の流れ

1. 発走前に入手した実出走表を `tools/real_race.py register` または `tools/ingest_daily.py` でSQLiteへ保存。
2. `tools/real_race.py baseline` で未学習の既存統計モデルを凍結。
3. `tools/mira_engine.py freeze --race <RACE_ID>` で**MIRAルールv1.0**の全2車単確率・本命・対抗・穴を上書き不可で保存する（日次取り込み時は2と3を自動実行）。
4. 私がチャットで個別に判断した独自予想は別の `tools/real_race.py predict` で保存する（ルール予想とは混同しない）。
5. 結果確定後に `tools/real_race.py settle` または `tools/settle_daily.py` で照合し、`tools/mira_engine.py report` で**同一レース**の予測精度を比較する。

初期レースの候補を確認するだけなら:

~~~sh
/usr/local/bin/python tools/mira_engine.py preview --race <RACE_ID>
~~~

`<RACE_ID>` は登録済み・未発走の実際のレースIDに置き換えてください。**発走後には新しい予測は作れません。** フィード取り込み済みのレースなら通常は自動で予想が固定されています。

## 現在の実装段階と限界

- v0.6：実戦とデモを分離し、統計モデルの確率予測を採点
- v0.7：発走前のMIRAチャット独自予想と根拠を保存
- v0.8：日次出走表JSONアダプタと時点管理、未発走レースの選別
- v0.9：確定着順・2車単払戻の厳密な突合（標準dry-run）
- **v1.0：実験的なMIRAルールの確率予測・根拠の凍結、既存モデルとのペア評価**

**学習済みAIモデルではありません。** v1.0の係数は未学習・未較正の仮説であり、的中率の改善や収益性は確認できていません。ChatGPT APIは未接続。投票機能もありません。

日次データの公開元に対する**二次利用・再配信の許諾は未確認**。公開されていることと自動収集の許可は異なります。利用権の確認なしに外部取得やcronを有効化しないでください。ツールには確認フラグがあり、それ自体は許可を意味しません。現在、さくらでの定期実行・実データ蓄積は未確認です。

## 詳しいドキュメント

- [MIRAモデル v1.0](docs/MIRA_V1.md)
- [出走表の登録 v0.8](docs/MIRA_V08.md)
- [結果の突合 v0.9](docs/MIRA_V09.md)
- [MIRA予想の保存 v0.7](docs/MIRA_V07.md)
- [学習・評価の設計 v0.6](docs/MIRA_RESEARCH.md)
- [TIPSTARウォッチ](docs/TIPSTAR_WATCH.md)

動作確認: `python3 -m unittest discover -s tests -v`。GitHub Actionsにも単体テストのジョブを定義しています。CIの完走確認は別途必要です。
