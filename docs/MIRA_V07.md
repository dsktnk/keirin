# KEIRIN LAB v0.7: MIRA実戦予想ワークフロー

今回の主眼はMIRA自身の予測精度を計測・改善すること。TIPSTAR予想師の情報収集から独立させる。

出走表の見方（公式）: https://www.keirin.jp/pc/static/beginner/basics/racecard.html

## できること

- 発走前に取得した一つの実レース出走表をJSONから登録する
- 現行の未学習モデルによる全2車単確率を発走前に固定する
- チャットでMIRAが検討した本命・対抗・穴と根拠を発走前に固定する
- 確定後の1〜3着と2車単の払戻を保存する
- 研究ページでMIRA本命の的中率・仮想回収率を表示する

外部データ自動取得・ChatGPT APIによる自動予想・自動投票はありません。出走情報とMIRAが作成する予想JSONは別途準備が必要です。値を推測で埋めないでください。以下は入力形式を示す例であり、実在レースではありません。

## 入力JSON 1: 出走表

3〜9人の全選手のデータが必要。rating=競走得点、win_rate=勝率、place_rate=2連対率で、割合は0〜1です（30%なら0.30）。line_idは同じラインの選手に共通の記号を付ける。captured_atは実際の観測時刻。

~~~json
{
  "race_id": "YOUR_RACE_ID",
  "venue": "実際の競輪場名",
  "race_no": 1,
  "class_name": "級班・レース名",
  "start_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "captured_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "source_url": "https://実際に確認した出走表URL",
  "entrants": [
    {
      "car_no": 1,
      "rider_name": "選手名",
      "rating": 85.5,
      "win_rate": 0.2,
      "place_rate": 0.4,
      "line_id": "A",
      "style": "逃"
    }
  ]
}
~~~

## 入力JSON 2: MIRA予想

MIRAと発走前に検討した予想を上書き不可で保存。picksは異なる2車単3点を本命・対抗・穴の順に記録する。confidenceはlow/medium/high。

~~~json
{
  "race_id": "YOUR_RACE_ID",
  "picks": ["12", "13", "21"],
  "confidence": "medium",
  "rationale": "実際の出走表を検証し、能力差やライン構成を比較して選択した根拠を詳しく記載する。"
}
~~~

## 入力JSON 3: 確定結果

金額は的中した2車単の100円あたり払戻。数字は形式上の例で、実際の結果を意味しません。

~~~json
{
  "race_id": "YOUR_RACE_ID",
  "first_no": 1,
  "second_no": 2,
  "third_no": 3,
  "payout_yen_per_100": 1000,
  "source_url": "https://実際に確認した結果URL"
}
~~~

## 操作

既存のクローン内で最新版に更新。SSH先の /home/dsktnk/www/keirin が Git クローンの場合も同様。

~~~bash
git pull origin main
~~~

確認済み実レースのJSONを準備し、発走前に以下の順番で実行する。ファイル名は説明用です。実際に作成したものを渡してください。

~~~bash
/usr/local/bin/python tools/real_race.py register --file ./local/real_racecard.json
/usr/local/bin/python tools/real_race.py baseline --race YOUR_RACE_ID
/usr/local/bin/python tools/real_race.py predict --file ./local/mira_prediction.json
~~~

発走・払戻確定後に実行。

~~~bash
/usr/local/bin/python tools/real_race.py settle --file ./local/real_result.json
/usr/local/bin/python tools/real_race.py report
/usr/local/bin/python tools/build_static.py
~~~

表示先: research.html （または index.cgi?view=research）。

- 入力時刻は原資料の観測値、予想保存時刻・結果保存時刻はサーバー側で固定する。
- 発走後の予想作成、過去予想の上書きを拒否する。
- 既存の架空デモを実戦実績に混ぜない。
- 発走前の事実のみで確率を凍結。結果確定後のデータを特徴量に混ぜない。
- データベースはGitHubにコミットしない。CGIは読み取り専用。
- 発走前に予想データが揃わなければそのレースは対象外にする。

## 次の段階

検証可能なデータ提供元からの取得・変換を自動化するアダプタ。実際に複数レースの結果が蓄積してから、レース条件別分析やウォークフォワード較正へ進む。初期モデルと実際のMIRA予想の精度を同じレース群で比較し、サンプル数と不確実性を明示する。

テスト: python3 -m unittest discover -s tests -v
