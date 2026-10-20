import csv
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
MODEL = 'feature-plackett-luce-v0.1'


def now_jst():
    return datetime.now(JST).isoformat(timespec='seconds')


def parse_time(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('日時にはタイムゾーンが必要です（例: +09:00）: ' + value)
    return dt.astimezone(JST)


def canonical_time(value):
    return parse_time(value).isoformat(timespec='seconds')


def connect(db_file, readonly=False):
    path = Path(db_file).expanduser().resolve()
    if readonly:
        con = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def init_db(con, schema_path):
    con.executescript(Path(schema_path).read_text(encoding='utf-8'))
    con.commit()


def checked_combo(value):
    if len(value) != 2 or any(c not in '123456789' for c in value) or value[0] == value[1]:
        raise ValueError('2車単comboは異なる車番2桁で指定: ' + repr(value))
    return value


CSV_FIELDS = {
    'races': ('id','race_date','venue','race_no','class_name','start_at','is_demo'),
    'entrants': ('race_id','car_no','rider_name','rating','win_rate','place_rate','line_id','style','captured_at'),
    'odds': ('race_id','bet_type','combo','decimal_odds','captured_at'),
    'tipsters': ('id','display_name','source','profile_url'),
    'picks': ('id','tipster_id','race_id','bet_type','combo','stake_yen','published_at','source_url'),
    'results': ('race_id','first_no','second_no','third_no','finalized_at'),
    'payouts': ('race_id','bet_type','combo','payout_yen_per_100'),
}
TIMES = {'start_at','captured_at','published_at','finalized_at'}
BET_TABLES = {'odds','picks','payouts'}


def import_csv(con, kind, path):
    if kind not in CSV_FIELDS:
        raise ValueError('未対応のCSV種別: ' + kind)
    fields = CSV_FIELDS[kind]
    # DBに直接取り込むのは運営者の手動操作のみ。公開CGIからは書き込めない。
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        rd = csv.DictReader(f)
        if rd.fieldnames is None or set(fields) - set(rd.fieldnames):
            raise ValueError('必要なCSV列: ' + ', '.join(fields))
        for n, item in enumerate(rd, start=2):
            try:
                row = {k: (item[k] if item[k] is not None else '') for k in fields}
                if any(row[k] == '' for k in fields if k not in ('class_name','line_id','style','profile_url','source_url','source')):
                    raise ValueError('必須列に空値')
                if kind in BET_TABLES:
                    if row['bet_type'] != '2車単':
                        raise ValueError('v0.1は2車単のみ対応')
                    checked_combo(row['combo'])
                if kind == 'entrants':
                    if not 0 <= float(row['win_rate']) <= float(row['place_rate']) <= 1:
                        raise ValueError('勝率 <= 連対率 <= 1が必要')
                if kind == 'races' and row['race_date'] != parse_time(row['start_at']).date().isoformat():
                    raise ValueError('開催日と発走日時の日付が一致しません')
                for key in TIMES & set(fields):
                    row[key] = canonical_time(row[key])
                if kind == 'races' and row['is_demo'] not in ('0','1'):
                    raise ValueError('is_demoは0または1')
                rows.append(tuple(row[k] for k in fields))
            except Exception as e:
                raise ValueError('{}:{}: {}'.format(path, n, e))
    cols = ','.join(fields)
    placeholders = ','.join('?' for _ in fields)
    # 既存スナップショットは上書きしない。競走結果の手動修正は別途監査フローで対応する。
    with con:
        con.executemany('INSERT INTO {} ({}) VALUES ({})'.format(kind, cols, placeholders), rows)
    return len(rows)


def entrants_at(con, race_id, at):
    return con.execute('SELECT * FROM entrants WHERE race_id=? AND captured_at<=? ORDER BY car_no',
                       (race_id, at)).fetchall()


def compute_probabilities(entrants):
    """Heuristic, NOT trained ML. Pairwise ordered finish probabilities sum to 1."""
    if len(entrants) < 2:
        raise ValueError('少なくとも2車の出走表が必要')
    scores = [float(e['rating']) for e in entrants]
    mu = sum(scores) / len(scores)
    sd = max(1.0, math.sqrt(sum((x-mu)**2 for x in scores)/len(scores)))
    win_mu = sum(float(e['win_rate']) for e in entrants)/len(entrants)
    place_mu = sum(float(e['place_rate']) for e in entrants)/len(entrants)
    strength = {}
    for e in entrants:
        score = (0.70*(float(e['rating'])-mu)/sd +
                 3.0*(float(e['win_rate'])-win_mu) +
                 1.5*(float(e['place_rate'])-place_mu))
        strength[str(e['car_no'])] = math.exp(max(-2.0, min(2.0, score)))
    total = sum(strength.values())
    raw = {}
    for a in entrants:
        for b in entrants:
            if a['car_no'] == b['car_no']:
                continue
            i, j = str(a['car_no']), str(b['car_no'])
            p = (strength[i]/total) * (strength[j]/(total-strength[i]))
            if a['line_id'] and a['line_id'] == b['line_id']:
                p *= 1.12  # same-line order is exploratory assumption, not a learned parameter
            raw[i+j] = p
    norm = sum(raw.values())
    return {k: v/norm for k,v in raw.items()}


def snapshot(con, race_id, at=None):
    at = canonical_time(at or now_jst())
    race = con.execute('SELECT * FROM races WHERE id=?', (race_id,)).fetchone()
    if race is None:
        raise ValueError('レースIDが不明です')
    if parse_time(at) >= parse_time(race['start_at']):
        raise ValueError('発走後の予測作成は禁止')
    if con.execute('SELECT 1 FROM forecasts WHERE race_id=? LIMIT 1',(race_id,)).fetchone():
        raise ValueError('予測スナップショットは保存済み。上書きは禁止')
    es = entrants_at(con, race_id, at)
    probabilities = compute_probabilities(es)
    with con:
        con.executemany('INSERT INTO forecasts VALUES (?,?,?,?,?,?)',
                        [(race_id,'2車単',k,p,MODEL,at) for k,p in probabilities.items()])
    return len(probabilities)


def settled_tipster_stats(con, cutoff=None, window=None):
    """Cutoff: only results finalized before the race being predicted; no future leakage."""
    cutoff = canonical_time(cutoff or now_jst())
    if window is not None and window not in (10,30):
        raise ValueError('予想師の履歴件数は10・30・全期間のみ')
    rows = con.execute('''
        SELECT p.tipster_id, t.display_name, p.race_id, p.combo, p.stake_yen,
               a.payout_yen_per_100, r.start_at
        FROM picks p JOIN tipsters t ON t.id=p.tipster_id
        JOIN races r ON r.id=p.race_id JOIN results z ON z.race_id=p.race_id
        LEFT JOIN payouts a ON a.race_id=p.race_id AND a.bet_type=p.bet_type AND a.combo=p.combo
        WHERE p.published_at<r.start_at AND z.finalized_at<=? AND r.start_at<?
        ORDER BY r.start_at DESC
    ''',(cutoff,cutoff)).fetchall()
    agg = defaultdict(lambda: {'name':'','races':set(),'stakes':0,'returns':0,'hit_races':set()})
    for row in rows:
        d = agg[row['tipster_id']]
        if window is not None and row['race_id'] not in d['races'] and len(d['races'])>=window:
            continue
        d['name'] = row['display_name']
        d['races'].add(row['race_id'])
        d['stakes'] += row['stake_yen']
        won = (row['payout_yen_per_100'] or 0)*row['stake_yen']/100
        d['returns'] += won
        if won > 0: d['hit_races'].add(row['race_id'])
    out = {}
    for key,d in agg.items():
        n = len(d['races'])
        roi = d['returns']/d['stakes'] if d['stakes'] else 0.0
        shrink = n/(n+30.0)
        # Strong short-window ROI from jackpots should not dominate consensus.
        adjusted = max(0.65,min(1.35,1.0+shrink*(min(3,roi)-1)))
        out[key] = {'id':key,'name':d['name'],'n':n,'stakes':d['stakes'],
                    'returns':int(d['returns']),'net':int(d['returns']-d['stakes']),
                    'roi':roi,'hit_rate':len(d['hit_races'])/n if n else 0,
                    'adjusted_weight':adjusted}
    return out


def odds_at(con, race_id, at):
    rows = con.execute('''
      SELECT o.combo,o.decimal_odds,o.captured_at FROM odds o
      WHERE o.race_id=? AND o.bet_type='2車単' AND o.captured_at<=?
      ORDER BY o.captured_at DESC''',(race_id,at)).fetchall()
    lookup = {}
    for r in rows:
        if r['combo'] not in lookup:
            lookup[r['combo']] = dict(r)
    return lookup


def analyze_race(con, race_id):
    race = con.execute('SELECT * FROM races WHERE id=?',(race_id,)).fetchone()
    if not race: raise ValueError('レースが見つかりません')
    forecast = con.execute('SELECT * FROM forecasts WHERE race_id=? ORDER BY probability DESC',(race_id,)).fetchall()
    if not forecast: return {'race':race,'entries':[],'ranked':[],'tipsters':[],'asof':None}
    asof = forecast[0]['snapshot_at']
    entries = entrants_at(con,race_id,asof)
    odds = odds_at(con,race_id,asof)
    stats = settled_tipster_stats(con,asof)
    picks = con.execute('''SELECT p.*,t.display_name FROM picks p JOIN tipsters t ON t.id=p.tipster_id
                         WHERE p.race_id=? AND p.bet_type='2車単' AND p.published_at<=?
                         AND p.published_at< ? ORDER BY t.display_name''',
                        (race_id,asof,race['start_at'])).fetchall()
    picks_by_tipster = defaultdict(list)
    for p in picks: picks_by_tipster[p['tipster_id']].append(p)
    support = defaultdict(float)
    for tid,items in picks_by_tipster.items():
        s = sum(i['stake_yen'] for i in items)
        weight = stats.get(tid,{}).get('adjusted_weight',1.0)
        for p in items:
            support[p['combo']] += weight * p['stake_yen']/s
    support_den = sum(stats.get(tid,{}).get('adjusted_weight',1.0) for tid in picks_by_tipster)
    ranked = []
    for f in forecast:
        p = float(f['probability'])
        od = odds.get(f['combo'])
        decimal_odds = float(od['decimal_odds']) if od else None
        ev = p*decimal_odds-1 if decimal_odds else None
        share = support[f['combo']]/support_den if support_den else 0
        # Unified ranking is a heuristic score, NOT a calibrated integrated probability.
        # Probability is the anchor; raw EV is unstable before calibration.
        max_probability = max(float(item['probability']) for item in forecast)
        rank_score = (0.45*(p/max_probability) + 0.35*share +
                      0.20*max(-1,min(1,ev))) if ev is not None else (-1+0.35*share)
        ranked.append({'combo':f['combo'],'prob':p,'odds':decimal_odds,
                       'ev':ev,'support':share,'support_n':sum(f['combo']==item['combo'] for item in picks),
                       'score':rank_score})
    ranked.sort(key=lambda r:(r['odds'] is not None,r['score'],r['prob']),reverse=True)
    # Only eligible pre-start picks participate in consensus. Source URL is NEVER fetched.
    return {'race':race,'entries':entries,'ranked':ranked,'tipsters':picks,'asof':asof}


def backtest(con):
    """Compare 3 fixed 100-yen strategies using the same frozen pre-race inputs."""
    rids = con.execute('''SELECT r.id FROM races r JOIN results z ON z.race_id=r.id
                            WHERE z.finalized_at<=? AND EXISTS(SELECT 1 FROM forecasts f
                            WHERE f.race_id=r.id AND f.snapshot_at<r.start_at)
                            ORDER BY r.start_at''',(now_jst(),)).fetchall()
    strategies = {key: {'races':0,'spent':0,'returned':0,'hits':0,'roi':None}
                  for key in ('integrated','model','tipster')}
    rows = []
    for item in rids:
        info = analyze_race(con,item['id'])
        ranked = [r for r in info['ranked'] if r['odds'] is not None]
        if not ranked: continue
        result = con.execute('SELECT * FROM results WHERE race_id=?',(item['id'],)).fetchone()
        winning_combo = str(result['first_no'])+str(result['second_no'])
        # Do not misinterpret missing payout records as a 0-yen losing ticket.
        winning_pay = con.execute('''SELECT payout_yen_per_100 FROM payouts
                                     WHERE race_id=? AND bet_type='2車単' AND combo=?''',
                                  (item['id'],winning_combo)).fetchone()
        if winning_pay is None: continue
        selected = {'integrated': ranked[0],
                    'model': max(ranked,key=lambda r:r['prob']),
                    'tipster': max(ranked,key=lambda r:r['support']) if any(r['support']>0 for r in ranked) else None}
        per_method = {}
        for method, pick in selected.items():
            if pick is None: continue
            payout = int(winning_pay['payout_yen_per_100']) if pick['combo']==winning_combo else 0
            d=strategies[method]
            d['races']+=1
            d['spent']+=100
            d['returned']+=payout
            d['hits']+=int(payout>0)
            per_method[method]={'combo':pick['combo'],'payout':payout,'prob':pick['prob']}
        best = selected['integrated']
        amount=per_method['integrated']['payout']
        rows.append({'race':info['race'],'combo':best['combo'],'payout':amount,
                     'net':amount-100,'odds':best['odds'],'prob':best['prob'],
                     'methods':per_method})
    for d in strategies.values():
        d['roi']=d['returned']/d['spent'] if d['spent'] else None
        d['hit_rate']=d['hits']/d['races'] if d['races'] else None
    n=len(rows)
    total=strategies['integrated']['returned']
    return {'rows':rows,'races':n,'spent':n*100,'returned':total,
            'roi':strategies['integrated']['roi'],
            'hit_rate':strategies['integrated']['hit_rate'],
            'strategies':strategies}
