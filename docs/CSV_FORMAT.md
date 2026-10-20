# CSVフィールド仕様（UTF-8 / BOM可）

実データの自動取得機構は **含まれません**。適法に取得・利用できるデータのみ入力してください。データはすべて日本時間の明示的なオフセット付き ISO 8601（例 `2026-10-21T17:00:00+09:00`）を使用します。

CSVは種別ごとに分割し、次の順番で読み込んでください。ヘッダー名は完全一致が必要です。

| 種別 | ヘッダー | 要点 |
|---|---|---|
| `races` | `id,race_date,venue,race_no,class_name,start_at,is_demo` | `is_demo=0`、レースIDは一意 |
| `entrants` | `race_id,car_no,rider_name,rating,win_rate,place_rate,line_id,style,captured_at` | 勝率・連対率は `0〜1`。取得時刻を保存 |
| `odds` | `race_id,bet_type,combo,decimal_odds,captured_at` | 2車単のみ、`combo` は `35` のような2桁。取得時点のオッズを行追加する |
| `tipsters` | `id,display_name,source,profile_url` | IDは文字列。許諾済みソースを記載 |
| `picks` | `id,tipster_id,race_id,bet_type,combo,stake_yen,published_at,source_url` | `stake_yen` は100円単位。公開された時刻を記録 |
| `results` | `race_id,first_no,second_no,third_no,finalized_at` | 確定情報のみ。取り込み後は修正フローが必要 |
| `payouts` | `race_id,bet_type,combo,payout_yen_per_100` | 的中した組み合わせだけを登録。払戻は100円当たり |

すべての `bet_type` は初期版では **`2車単`** に固定しています。CSVインポートは原則 INSERT ONLY。既存IDを上書きしません。オッズは `(race_id, bet_type, combo, captured_at)` を主キーとするので、異なる時刻の価格情報を保存可能です。

## 1レースの最小例

`races.csv`
```csv
id,race_date,venue,race_no,class_name,start_at,is_demo
sample_20261021_01,2026-10-21,松阪,1,A級予選,2026-10-21T17:00:00+09:00,0
```

`entrants.csv`（実際は出走車をすべて入力）
```csv
race_id,car_no,rider_name,rating,win_rate,place_rate,line_id,style,captured_at
sample_20261021_01,1,例選手A,90.3,0.21,0.41,1,逃,2026-10-21T15:00:00+09:00
sample_20261021_01,2,例選手B,87.2,0.15,0.38,1,追,2026-10-21T15:00:00+09:00
```

`tipsters.csv`
```csv
id,display_name,source,profile_url
manual01,手動登録例,manual,
```

`picks.csv`
```csv
id,tipster_id,race_id,bet_type,combo,stake_yen,published_at,source_url
pick001,manual01,sample_20261021_01,2車単,12,100,2026-10-21T15:10:00+09:00,
```

`odds.csv`
```csv
race_id,bet_type,combo,decimal_odds,captured_at
sample_20261021_01,2車単,12,6.2,2026-10-21T15:15:00+09:00
```

予測生成時、**出走表の `captured_at` が予測時刻以前であること**が条件。オッズの参照も予測スナップショット時刻までに制限されます。予想師の集計には、予測対象レースより前に確定した履歴のみ利用します。

v0.1未対応: 払戻金の返還・特払い、失格訂正、別表券種、ラインの多段階関係、取消後のスナップショットや払戻率変更。これらを含むレースは検証対象から外してください。
