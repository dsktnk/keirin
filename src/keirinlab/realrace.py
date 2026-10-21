"""Real-race operator workflow for MIRA's pre-start analysis.

No web scraping, authentication, AI API calls, or ticket purchases.
The operator supplies verified public racecard facts and MIRA's authored picks.
"""
import html
import json
import math
import re
from datetime import datetime
from urllib.parse import urlsplit
from .core import canonical_time, now_jst, parse_time, snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_race_sources (
  race_id TEXT PRIMARY KEY REFERENCES races(id),
  source_url TEXT NOT NULL,
  captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mira_predictions (
  race_id TEXT PRIMARY KEY REFERENCES races(id),
  predicted_at TEXT NOT NULL,
  best_combo TEXT NOT NULL,
  second_combo TEXT NOT NULL,
  third_combo TEXT NOT NULL,
  confidence TEXT NOT NULL,
  rationale TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS real_race_settlements (
  race_id TEXT PRIMARY KEY REFERENCES races(id),
  source_url TEXT NOT NULL,
  recorded_at TEXT NOT NULL
);
"""
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def setup(con):
    con.executescript(SCHEMA)


def require_obj(data):
    if not isinstance(data, dict):
        raise ValueError('JSONはオブジェクトで指定してください')
    return data


def as_text(value, field, maxlen=120):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maxlen or any(ord(c) < 32 for c in value):
        raise ValueError(field+' は空でない文字列を指定してください')
    return value.strip()


def source_url(value):
    s = as_text(value, 'source_url', 1500)
    u = urlsplit(s)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError('source_url は認証情報を含まないHTTPS URLにしてください')
    return s


def race_id(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('race_id は英数字・_・- の80文字以内で指定')
    return value


def number(value, field, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(field+' は数値で指定')
    n = float(value)
    if not math.isfinite(n) or not lo <= n <= hi:
        raise ValueError(field+' が範囲外')
    return n


def strict_int(value, field, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(field+' は整数で指定')
    return value


def at_time(value, field):
    if not isinstance(value, str):
        raise ValueError(field+' にタイムゾーン付き日時が必要')
    return canonical_time(value)


def register_race(con, data, at=None):
    """Create one immutable real racecard. It must have been observed before start."""
    data = require_obj(data)
    now = parse_time(at or now_jst())
    rid = race_id(data.get('race_id'))
    venue = as_text(data.get('venue'), 'venue', 60)
    no = strict_int(data.get('race_no'), 'race_no', 1, 12)
    cls = data.get('class_name', '')
    if not isinstance(cls, str) or len(cls) > 80:
        raise ValueError('class_name が不正')
    start = at_time(data.get('start_at'), 'start_at')
    captured = at_time(data.get('captured_at'), 'captured_at')
    if not parse_time(captured) <= now < parse_time(start):
        raise ValueError('出走表は観測後かつ発走前にだけ登録できます')
    src = source_url(data.get('source_url'))
    entrants = data.get('entrants')
    if not isinstance(entrants, list) or not 3 <= len(entrants) <= 9:
        raise ValueError('出走選手は3〜9人必要です')
    parsed = []
    for item in entrants:
        item = require_obj(item)
        car = strict_int(item.get('car_no'), 'car_no', 1, 9)
        name = as_text(item.get('rider_name'), 'rider_name', 120)
        rating = number(item.get('rating'), 'rating', 0, 150)
        wr = number(item.get('win_rate'), 'win_rate (0〜1)', 0, 1)
        pr = number(item.get('place_rate'), 'place_rate (0〜1)', 0, 1)
        if wr > pr:
            raise ValueError('win_rate は place_rate 以下で指定してください')
        line = item.get('line_id', '')
        style = item.get('style', '')
        if not isinstance(line, str) or len(line) > 40 or not isinstance(style, str) or len(style) > 30:
            raise ValueError('line_id/style が不正')
        parsed.append((rid, car, name, rating, wr, pr, line, style, captured))
    if len({row[1] for row in parsed}) != len(parsed):
        raise ValueError('車番が重複しています')
    if data.get('is_demo') not in (None, False):
        raise ValueError('実戦レースにデモフラグは指定できません')
    race_fields = (rid, parse_time(start).date().isoformat(), venue, no, cls, start, 0)
    setup(con)
    with con:
        previous = con.execute('SELECT * FROM races WHERE id=?', (rid,)).fetchone()
        if previous:
            old_rows = con.execute('SELECT * FROM entrants WHERE race_id=? ORDER BY car_no', (rid,)).fetchall()
            old_src = con.execute('SELECT source_url,captured_at FROM real_race_sources WHERE race_id=?', (rid,)).fetchone()
            if (tuple(previous) != race_fields or sorted(tuple(x) for x in old_rows) != sorted(parsed)
                    or old_src is None or tuple(old_src) != (src, captured)):
                raise ValueError('既存レースの内容は上書きできません: '+rid)
            return 'unchanged'
        con.execute('INSERT INTO races VALUES (?,?,?,?,?,?,?)', race_fields)
        con.executemany('INSERT INTO entrants VALUES (?,?,?,?,?,?,?,?,?)', parsed)
        con.execute('INSERT INTO real_race_sources VALUES (?,?,?)', (rid, src, captured))
    return 'created'


def baseline(con, rid, at=None):
    race_id(rid)
    setup(con)
    race = con.execute('SELECT is_demo FROM races WHERE id=?', (rid,)).fetchone()
    if not race or race['is_demo'] or not con.execute('SELECT 1 FROM real_race_sources WHERE race_id=?',(rid,)).fetchone():
        raise ValueError('登録済みの実戦レースのみ対象です')
    return snapshot(con, rid, at or now_jst())


def predict_mira(con, data, at=None):
    """Operator records MIRA's original top-3 ordered combos before start."""
    data = require_obj(data)
    rid = race_id(data.get('race_id'))
    now = at_time(at or now_jst(), 'predicted_at')
    picks = data.get('picks')
    if not isinstance(picks, list) or len(picks) != 3 or len(set(picks)) != 3:
        raise ValueError('本命・対抗・穴の異なる2車単3点を指定')
    confidence = data.get('confidence', 'medium')
    if confidence not in ('low','medium','high'):
        raise ValueError('confidence は low / medium / high')
    rationale = as_text(data.get('rationale'), 'rationale', 2000)
    if len(rationale) < 15:
        raise ValueError('rationale は15文字以上にしてください')
    setup(con)
    race = con.execute('SELECT start_at,is_demo FROM races WHERE id=?',(rid,)).fetchone()
    if not race or race['is_demo'] or not con.execute('SELECT 1 FROM real_race_sources WHERE race_id=?',(rid,)).fetchone():
        raise ValueError('登録済みの実戦レースのみ対象')
    if parse_time(now) >= parse_time(race['start_at']):
        raise ValueError('発走後に予想を保存できません')
    car_set = {str(row['car_no']) for row in con.execute('SELECT car_no FROM entrants WHERE race_id=?',(rid,))}
    if any(not isinstance(p,str) or len(p)!=2 or p[0]==p[1] or any(c not in car_set for c in p) for p in picks):
        raise ValueError('出走車番から2車単を選んでください')
    if con.execute('SELECT 1 FROM mira_predictions WHERE race_id=?',(rid,)).fetchone():
        raise ValueError('MIRA予想は上書きできません')
    # For comparable evaluations, require an already-frozen probabilistic baseline.
    f = con.execute('SELECT snapshot_at FROM forecasts WHERE race_id=? LIMIT 1',(rid,)).fetchone()
    if not f or parse_time(f['snapshot_at']) > parse_time(now):
        raise ValueError('先に baseline で発走前の比較モデル予測を固定してください')
    with con:
        con.execute('INSERT INTO mira_predictions VALUES (?,?,?,?,?,?,?)',
                    (rid,now,picks[0],picks[1],picks[2],confidence,rationale))
    return now


def settle_race(con, data, at=None):
    data = require_obj(data)
    rid = race_id(data.get('race_id'))
    now = at_time(at or now_jst(), 'recorded_at')
    winner = [strict_int(data.get(k),k,1,9) for k in ('first_no','second_no','third_no')]
    if len(set(winner)) != 3:
        raise ValueError('上位3車の車番が重複しています')
    pay = strict_int(data.get('payout_yen_per_100'), 'payout_yen_per_100', 100, 100000000)
    src = source_url(data.get('source_url'))
    setup(con)
    race = con.execute('SELECT start_at,is_demo FROM races WHERE id=?',(rid,)).fetchone()
    if not race or race['is_demo'] or not con.execute('SELECT 1 FROM real_race_sources WHERE race_id=?',(rid,)).fetchone():
        raise ValueError('登録済み実戦レースのみ結果を保存できます')
    if parse_time(now) <= parse_time(race['start_at']):
        raise ValueError('発走前の結果登録はできません')
    cars = {row['car_no'] for row in con.execute('SELECT car_no FROM entrants WHERE race_id=?',(rid,))}
    if not set(winner) <= cars:
        raise ValueError('着順に出走していない車番があります')
    if con.execute('SELECT 1 FROM results WHERE race_id=?',(rid,)).fetchone():
        raise ValueError('既に結果が登録されています。上書き禁止')
    with con:
        con.execute('INSERT INTO results VALUES (?,?,?,?,?)', (rid,*winner,now))
        con.execute('INSERT INTO payouts VALUES (?,?,?,?)',
                    (rid,'2車単',str(winner[0])+str(winner[1]),pay))
        con.execute('INSERT INTO real_race_settlements VALUES (?,?,?)',(rid,src,now))
    return 'settled'


def mira_summary(con):
    setup(con)
    rows = con.execute("""
      SELECT m.*, r.venue, r.race_date, r.race_no, r.start_at,
             z.first_no, z.second_no, z.finalized_at,
             p.payout_yen_per_100
      FROM mira_predictions m
      JOIN races r ON r.id=m.race_id AND r.is_demo=0
      LEFT JOIN results z ON z.race_id=m.race_id
      LEFT JOIN payouts p ON p.race_id=m.race_id AND p.bet_type='2車単'
        AND p.combo=(CAST(z.first_no AS TEXT)||CAST(z.second_no AS TEXT))
      ORDER BY r.start_at DESC
    """).fetchall()
    now = parse_time(now_jst())
    entries = []
    for r in rows:
        status = 'pending'
        payoff = None
        if r['finalized_at'] and parse_time(r['finalized_at']) <= now:
            status = 'settled'
            winning = str(r['first_no'])+str(r['second_no'])
            if r['payout_yen_per_100'] is not None:
                payoff = int(r['payout_yen_per_100']) if winning == r['best_combo'] else 0
        entries.append({'race_id':r['race_id'],'venue':r['venue'],
                        'date':r['race_date'],'race_no':r['race_no'],
                        'best':r['best_combo'],'second':r['second_combo'],'third':r['third_combo'],
                        'predicted_at':r['predicted_at'],'confidence':r['confidence'],
                        'rationale':r['rationale'],'status':status,'payoff':payoff,
                        'hit':None if status=='pending' else
                        int(r['best_combo']==str(r['first_no'])+str(r['second_no']))})
    settled = [v for v in entries if v['status']=='settled']
    paid = [v for v in settled if v['payoff'] is not None]
    return {'total':len(entries),'settled':len(settled),'paid':len(paid),
            'hits':sum(v['hit'] for v in settled),
            'hit_rate':sum(v['hit'] for v in settled)/len(settled) if settled else None,
            'roi':sum(v['payoff'] for v in paid)/(100*len(paid)) if paid else None,
            'entries':entries}


def mira_panel(con):
    s = mira_summary(con)
    pct = lambda x: '{:.1f}%'.format(100*x) if x is not None else '—'
    out = ('<section class="panel"><h2>MIRAの発走前予想（実戦のみ）</h2>'
           '<p class="muted">対話で作った予想を保存する形式。AIによる自動予想は未接続。'
           '架空データは含めません。1点100円仮想購入の回収率です。</p>'
           '<p>保存 <b>{}</b>件 ／ 確定 <b>{}</b>件 ／ 本命的中 <b>{}</b>件'
           ' ／ 的中率 <b>{}</b> ／ 照合可能回収率 <b>{}</b></p>').format(
        s['total'],s['settled'],s['hits'],pct(s['hit_rate']),pct(s['roi']))
    if not s['entries']:
        return out+'<p class="muted">実レースの予想がまだありません。登録→基準予測→MIRA予想の順に追加できます。</p></section>'
    out += ('<div class="tablewrap"><table><thead><tr><th>開催</th><th>本命</th>'
            '<th>対抗・穴</th><th>自信度</th><th>判定</th><th>予想根拠</th></tr></thead><tbody>')
    for row in s['entries'][:30]:
        state = '未確定' if row['status']=='pending' else ('的中' if row['hit'] else '不的中')
        out += '<tr><td>{} {} {}R</td><td>{}</td><td>{} / {}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
            html.escape(row['date']),html.escape(row['venue']),row['race_no'],
            html.escape(row['best']),html.escape(row['second']),
            html.escape(row['third']),html.escape(row['confidence']),state,
            html.escape(row['rationale']))
    return out+'</tbody></table></div></section>'
