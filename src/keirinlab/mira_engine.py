"""MIRA rule-engine v1.0: an experimental, deterministic 2車単 challenger.

Distinct from ChatGPT's authored picks. Coefficients are *hypotheses*, not trained
parameters; no promise of predictive advantage. Python 3.8 / stdlib / SQLite.
"""
import html
import json
import math
from collections import defaultdict
from .core import now_jst, parse_time, canonical_time

VERSION = 'mira-rule-v1.0'
SCHEMA = """
CREATE TABLE IF NOT EXISTS mira_rule_forecasts (
  race_id TEXT NOT NULL REFERENCES races(id),
  combo TEXT NOT NULL,
  probability REAL NOT NULL CHECK(probability > 0 AND probability <= 1),
  snapshot_at TEXT NOT NULL,
  model_version TEXT NOT NULL,
  PRIMARY KEY (race_id, combo)
);
CREATE TABLE IF NOT EXISTS mira_rule_decisions (
  race_id TEXT PRIMARY KEY REFERENCES races(id),
  snapshot_at TEXT NOT NULL,
  model_version TEXT NOT NULL,
  best_combo TEXT NOT NULL,
  second_combo TEXT NOT NULL,
  third_combo TEXT NOT NULL,
  confidence TEXT NOT NULL,
  rationale TEXT NOT NULL
);
"""


def setup(con):
    con.executescript(SCHEMA)


def _scale(values, floor):
    mu = sum(values) / len(values)
    std = max(floor, math.sqrt(sum((v-mu)**2 for v in values)/len(values)))
    return [(v-mu)/std for v in values]


def _clamp(value):
    return min(2.5, max(-2.5, value))


def compute(entrants):
    """Only pre-start available score/win/top2, plus *confirmed* line IDs.

    Construct separate win and runner-up strengths with a Plackett-Luce-style
    conditional normalization, then normalize the ordered-pair distribution.
    """
    if not 3 <= len(entrants) <= 9:
        raise ValueError('3〜9車立てのみ対応')
    car_ids = []
    scores = []
    wins = []
    places = []
    lines = []
    for e in entrants:
        car = e['car_no']
        if type(car) is not int or not 1 <= car <= 9 or car in car_ids:
            raise ValueError('車番が重複または不正')
        car_ids.append(car)
        score, win, place = (float(e['rating']),float(e['win_rate']),float(e['place_rate']))
        if not (math.isfinite(score) and 0 <= score <= 150
                and math.isfinite(win) and 0 <= win <= 1
                and math.isfinite(place) and 0 <= place <= 1
                and win <= place + 0.000001):
            raise ValueError('競走得点・勝率・2連対率が不正')
        scores.append(score)
        wins.append(win)
        places.append(place)
        line = e['line_id'] or ''
        if not isinstance(line,str):
            raise ValueError('line_idが不正')
        lines.append(line)
    zr=_scale(scores, 2.0)
    zw=_scale(wins, 0.05)
    zp=_scale(places, 0.07)
    # Hand-chosen experimental coefficients; revise only by changing VERSION.
    first=[math.exp(_clamp(.68*zr[k]+.40*zw[k]+.12*zp[k])) for k in range(len(car_ids))]
    second=[math.exp(_clamp(.52*zr[k]+.12*zw[k]+.40*zp[k])) for k in range(len(car_ids))]
    sf=sum(first)
    ss=sum(second)
    raw={}
    for i,car in enumerate(car_ids):
        for j,other in enumerate(car_ids):
            if i==j:
                continue
            pair=str(car)+str(other)
            prob=(first[i]/sf)*(second[j]/(ss-second[i]))
            if lines[i] and lines[i]==lines[j]:
                prob*=1.10  # hypothetical line synergy; no guessed lines
            raw[pair]=prob
    total=sum(raw.values())
    return {key:value/total for key,value in raw.items()}


def prediction(entrants):
    prob=compute(entrants)
    top=sorted(prob,key=lambda key:(-prob[key],key))
    # Until genuine calibration, never mark a pick 'high confidence'.
    ratio=prob[top[0]]/prob[top[1]]
    confidence='medium' if ratio>=1.35 else 'low'
    by_car={str(e['car_no']):e for e in entrants}
    leader=top[0]
    a=by_car[leader[0]]
    b=by_car[leader[1]]
    gap=round(float(a['rating'])-float(b['rating']),2)
    line=('同一ライン確認済み' if a['line_id'] and a['line_id']==b['line_id']
          else '同一ラインの確認なし')
    rationale=('未学習のMIRAルールv1.0による候補。'
               '競走得点・勝率・2連対率を1着と2着で異なる重みとして評価。'
               '本命{}：先頭候補{}（競走得点{:.2f}）、'
               '2着候補{}（競走得点{:.2f}）、得点差{:+.2f}。'
               '{}。予測確率{:.1f}%（未較正）、比較検証が必要。').format(
               leader, a['rider_name'],float(a['rating']),
               b['rider_name'],float(b['rating']),gap,
               line,100*prob[leader])
    return {'model_version':VERSION,'picks':top[:3],
            'confidence':confidence,'rationale':rationale,
            'probabilities':prob,'top1_probability':prob[top[0]]}


def _exists(con,table):
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)
    ).fetchone())


def preview(con,race_id,at=None):
    timestamp=canonical_time(at or now_jst())
    race=con.execute('SELECT id,start_at,is_demo FROM races WHERE id=?',(race_id,)).fetchone()
    if race is None or race['is_demo']!=0:
        raise ValueError('登録済みの実レースのみ対象')
    if not _exists(con,'real_race_sources') or not con.execute(
        'SELECT 1 FROM real_race_sources WHERE race_id=?',(race_id,)
    ).fetchone():
        raise ValueError('出走表の取得元が確認できません')
    if parse_time(timestamp)>=parse_time(race['start_at']):
        raise ValueError('発走後の予測は禁止')
    entrants=con.execute('SELECT * FROM entrants WHERE race_id=? ORDER BY car_no',(race_id,)).fetchall()
    if not entrants or any(parse_time(e['captured_at'])>parse_time(timestamp) for e in entrants):
        raise ValueError('発走前に確認済みの出走情報が不足しています')
    result=prediction(entrants)
    result['race_id']=race_id
    result['snapshot_at']=timestamp
    return result


def freeze(con,race_id,at=None):
    """Immutable engine snapshot independent of human-authored MIRA picks."""
    if _exists(con,'mira_rule_decisions') and con.execute(
        'SELECT 1 FROM mira_rule_decisions WHERE race_id=?',(race_id,)
    ).fetchone():
        raise ValueError('MIRAルールの予測は保存済みです。上書き禁止')
    p=preview(con,race_id,at=at)
    # A still-valid baseline permits paired comparison over identical races.
    rows=con.execute('SELECT snapshot_at FROM forecasts WHERE race_id=?',(race_id,)).fetchall()
    if not rows or any(parse_time(row['snapshot_at'])>parse_time(p['snapshot_at']) for row in rows):
        raise ValueError('まず比較モデルの発走前スナップショットを保存してください')
    setup(con)
    with con:
        con.executemany(
            'INSERT INTO mira_rule_forecasts VALUES (?,?,?,?,?)',
            [(race_id,k,v,p['snapshot_at'],VERSION)
             for k,v in p['probabilities'].items()])
        con.execute('INSERT INTO mira_rule_decisions VALUES (?,?,?,?,?,?,?,?)',
                    (race_id,p['snapshot_at'],VERSION,*p['picks'],
                     p['confidence'],p['rationale']))
    return p


def _valid_prob(rows,expected,cutoff,start):
    if len(rows)!=len(expected):
        return None
    if len({(r['snapshot_at'],r['model_version']) for r in rows})!=1:
        return None
    snap=parse_time(rows[0]['snapshot_at'])
    if snap>=start or snap>cutoff:
        return None
    dist={r['combo']:float(r['probability']) for r in rows}
    if (len(dist)!=len(rows) or set(dist)!=expected
            or not all(math.isfinite(v) and 0<v<=1 for v in dist.values())
            or abs(sum(dist.values())-1)>1e-5):
        return None
    return dist


def paired_scorecard(con,now=None):
    """Outcome-blind input, same held-out real races for both models."""
    cutoff=parse_time(now or now_jst())
    if not _exists(con,'mira_rule_forecasts'):
        return {'n':0,'baseline':None,'mira':None,'venues':[],'excluded':{}}
    races=con.execute("""
      SELECT r.id,r.venue,r.start_at,z.first_no,z.second_no,z.finalized_at
      FROM races r JOIN results z ON r.id=z.race_id
      JOIN mira_rule_decisions m ON m.race_id=r.id
      WHERE r.is_demo=0 ORDER BY r.start_at,r.id
    """).fetchall()
    scores={'baseline':[],'mira':[]}
    venues=defaultdict(lambda:{'n':0,'base_hits':0,'mira_hits':0})
    excluded=defaultdict(int)
    for race in races:
        start=parse_time(race['start_at'])
        if parse_time(race['finalized_at'])>cutoff or parse_time(race['finalized_at'])<=start:
            excluded['result_not_valid']+=1;continue
        entries=con.execute('SELECT car_no,captured_at FROM entrants WHERE race_id=?',(race['id'],)).fetchall()
        if len(entries)<3 or len({x['car_no'] for x in entries})!=len(entries):
            excluded['entrants_invalid']+=1;continue
        cars=[str(e['car_no']) for e in entries]
        expected={a+b for a in cars for b in cars if a!=b}
        winning=str(race['first_no'])+str(race['second_no'])
        if winning not in expected:
            excluded['winner_invalid']+=1;continue
        base=con.execute("SELECT combo,probability,snapshot_at,model_version FROM forecasts WHERE race_id=? AND bet_type='2車単'",(race['id'],)).fetchall()
        mira=con.execute("SELECT combo,probability,snapshot_at,model_version FROM mira_rule_forecasts WHERE race_id=?",(race['id'],)).fetchall()
        d1=_valid_prob(base,expected,cutoff,start)
        d2=_valid_prob(mira,expected,cutoff,start)
        if d1 is None or d2 is None:
            excluded['forecast_invalid']+=1;continue
        if any(parse_time(e['captured_at'])>min(parse_time(base[0]['snapshot_at']),parse_time(mira[0]['snapshot_at'])) for e in entries):
            excluded['future_features']+=1;continue
        payout=con.execute("SELECT payout_yen_per_100 FROM payouts WHERE race_id=? AND bet_type='2車単' AND combo=?",(race['id'],winning)).fetchone()
        for label,dist in (('baseline',d1),('mira',d2)):
            rank=sorted(dist,key=lambda k:(-dist[k],k))
            scores[label].append({
                'hit':int(rank[0]==winning),
                'top3':int(winning in rank[:3]),
                'logloss':-math.log(dist[winning]),
                'brier':sum((v-(1.0 if k==winning else 0.0))**2 for k,v in dist.items()),
                'payout':(payout['payout_yen_per_100'] if rank[0]==winning else 0)
                    if payout else None
            })
        v=venues[race['venue']]
        v['n']+=1
        v['base_hits']+=scores['baseline'][-1]['hit']
        v['mira_hits']+=scores['mira'][-1]['hit']
    def aggregate(rows):
        n=len(rows)
        if not n:
            return None
        paid=[r for r in rows if r['payout'] is not None]
        return {
            'n':n, 'hits':sum(r['hit'] for r in rows),
            'hit_rate':sum(r['hit'] for r in rows)/n,
            'top3_rate':sum(r['top3'] for r in rows)/n,
            'logloss':sum(r['logloss'] for r in rows)/n,
            'brier':sum(r['brier'] for r in rows)/n,
            'paid':len(paid),
            'roi':sum(r['payout'] for r in paid)/(100*len(paid)) if paid else None
        }
    return {'n':len(scores['baseline']),
            'baseline':aggregate(scores['baseline']),
            'mira':aggregate(scores['mira']),
            'venues':[dict(venue=k,**v) for k,v in sorted(venues.items())],
            'excluded':dict(excluded)}


def panel(con):
    exists=_exists(con,'mira_rule_decisions')
    saved=con.execute('SELECT COUNT(*) FROM mira_rule_decisions').fetchone()[0] if exists else 0
    stats=paired_scorecard(con)
    p=lambda x: '{:.1f}%'.format(x*100) if x is not None else '—'
    out=('<section class="panel"><h2>MIRAルール予想 v1.0（実験）</h2>'
         '<p>発走前予測の凍結：<b>{}</b>レース ／ 結果まで比較可能：<b>{}</b>レース</p>'
         '<p class="muted">AI APIとは未接続。係数は仮説で、学習・較正されていません。'
         '私がチャットで独自に判断した予想とは区別しています。</p>').format(saved,stats['n'])
    if stats['n']:
        out+='<div class="tablewrap"><table><thead><tr><th>指標</th><th>既存モデル</th><th>MIRAルール</th></tr></thead><tbody>'
        for key,label,formatter in [
          ('hit_rate','本命1点的中率',p),('top3_rate','上位3点内的中率',p),
          ('logloss','平均対数損失',lambda x:'{:.3f}'.format(x)),
          ('brier','平均Brierスコア',lambda x:'{:.3f}'.format(x)),
          ('roi','100円1点仮想回収率',p)]:
            values=[]
            for side in ('baseline','mira'):
                v=stats[side][key]
                values.append(formatter(v) if v is not None else '—')
            out+='<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(label,*values)
        out+='</tbody></table></div>'
        out+='<p class="muted">両モデルで同じ実レースだけを比較。少数サンプルでは優劣を判定できません。</p>'
    else:
        out+='<p class="muted">まだ検証可能な実レースがありません。発走前の凍結予測と確定結果が両方必要です。</p>'
    if exists and saved:
        recent=con.execute("""
          SELECT m.best_combo,m.second_combo,m.third_combo,m.confidence,m.rationale,
                 m.snapshot_at,r.venue,r.race_no,r.start_at,
                 z.first_no,z.second_no,z.finalized_at
          FROM mira_rule_decisions m JOIN races r ON r.id=m.race_id
          LEFT JOIN results z ON z.race_id=r.id
          WHERE r.is_demo=0
          ORDER BY r.start_at DESC LIMIT 20
        """).fetchall()
        out+='<h3>保存済みの予想候補（最新20レース）</h3>'
        out+='<div class="tablewrap"><table><thead><tr><th>競輪場・R</th><th>発走予定</th><th>本命</th><th>対抗</th><th>穴</th><th>結果</th></tr></thead><tbody>'
        now=parse_time(now_jst())
        for r in recent:
            settled=r['finalized_at'] and parse_time(r['finalized_at'])<=now
            status=('的中' if r['best_combo']==str(r['first_no'])+str(r['second_no']) else '不的中') if settled else '未確定'
            out+='<tr><td>{} {}R</td><td>{}</td><td><b>{}</b></td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                html.escape(r['venue']),r['race_no'],
                html.escape(r['start_at']),html.escape(r['best_combo']),
                html.escape(r['second_combo']),html.escape(r['third_combo']),status)
        out+='</tbody></table></div>'
        out+='<p class="muted">これらは実験的なルール予測であり、ChatGPTが個別レースの展開を判断した結果ではありません。</p>'
    return out+'</section>'
