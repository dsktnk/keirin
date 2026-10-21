# KEIRIN LAB v0.9 — 結果と2車単払戻の照合

実装: src/keirinlab/resultsfeed.py と tools/settle_daily.py
結果JSON形式参考: https://github.com/kurinaka12-afk/keirin-app-data

出走表とは異なる配信元のため、レースID(12桁)、開催日、競輪場、レース番号、上位着順の車番、2車単の的中組合せと払戻を照合する。
発走後15分以内、着順未確定、同着の疑い、払戻不一致、レース不一致は保存しない。既存結果は上書きしない。
標準はdry-run。--commitを指定した時だけSQLiteへ書き込む。
外部リポジトリの公開はデータ再利用許可を意味しない。権利・利用条件を確認してから収集・保存すること。cronは未設定。

## 使い方

既存クローンで git pull origin main

診断（ファイルが実在する場合）:
python3 tools/settle_daily.py --file ./local/results.json --date 2026-10-21

取得診断（利用条件の確認後）:
python3 tools/settle_daily.py --fetch --date 2026-10-21 --source-rights-confirmed

保存（利用許可を確認したファイルと出典URLを指定）:
python3 tools/settle_daily.py --file ./local/results.json --date 2026-10-21 --source-url https://example.org/authorized-results.json --source-rights-confirmed --commit

対象日は実際に保存した発走前の出走表と一致する日に置き換える。許諾フラグだけで利用権が発生するわけではない。
予想・出走表が存在しないレースに後付けで予想を作らない。発走前に予想を固定したレースのみ評価できる。
研究画面は index.cgi?view=research または tools/build_static.py で再生成した research.html。
テスト: python3 -m unittest discover -s tests -v。さくら実機での検証は未実施。
