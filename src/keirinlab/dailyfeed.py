"""Daily pre-race JSON adapter (schema: snarfnet/keirin-data entries_YYYYMMDD.json).

A public repository does NOT necessarily grant reuse rights. The operator must
confirm source permission before running persistent/automated ingestion.
No result fields, predicted bets or undocumented line topology are imported.
"""
import json
import math
import re
from datetime import datetime, timedelta
from .core import JST, now_jst, parse_time
from .realrace import register_race, baseline

MAX_PAYLOAD = 2 * 1024 * 1024
RACE_ID = re.compile(r'[A-Za-z0-9_-]{1,50}\Z')
CLOCK = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d\Z')


def _rate(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(field+' は数値の百分率が必要')
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 100:
        raise ValueError(field+' は0～100%の範囲')
    return round(float(value)/100, 6)


def _card(row, day, observed_at, url):
    if not isinstance(row, dict):
        raise ValueError('レース情報がオブジェクトではありません')
    rid = str(row.get('race_id',''))
    if not RACE_ID.fullmatch(rid):
        raise ValueError('race_id が不正')
    race_no = row.get('race_no')
    if isinstance(race_no, bool) or not isinstance(race_no, int) or not 1 <= race_no <= 12:
        raise ValueError('race_no が不正')
    venue = row.get('venue')
    if not isinstance(venue,str) or not 1 <= len(venue.strip()) <= 60:
        raise ValueError('競輪場名が不正')
    clock = row.get('start_time')
    if not isinstance(clock,str) or not CLOCK.fullmatch(clock):
        raise ValueError('発走予定時刻が不正')
    start_at = datetime.strptime(day+'T'+clock, '%Y-%m-%dT%H:%M').replace(tzinfo=JST)
    entries = row.get('entries')
    if not isinstance(entries, list) or not 3 <= len(entries) <= 9:
        raise ValueError('出走選手が3～9人ではありません')
    output = []
    cars = set()
    for entry in entries:
        if not isinstance(entry,dict):
            raise ValueError('出走者がオブジェクトではありません')
        car = entry.get('umaban')
        if isinstance(car,bool) or not isinstance(car,int) or not 1 <= car <= 9 or car in cars:
            raise ValueError('車番に欠損または重複')
        cars.add(car)
        name = entry.get('name')
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError('選手名が不正')
        rating = entry.get('score')
        if isinstance(rating,bool) or not isinstance(rating,(int,float)) or not math.isfinite(float(rating)) or not 0 <= rating <= 150:
            raise ValueError('競走得点が不正')
        win = _rate(entry.get('win_rate'), '勝率')
        top2 = _rate(entry.get('top2_rate'), '2連対率')
        if win > top2 + 0.000001:
            raise ValueError('勝率が2連対率を超えています')
        style = entry.get('style','')
        if not isinstance(style,str) or len(style) > 30:
            raise ValueError('脚質が不正')
        output.append({
            'car_no':car, 'rider_name':name.strip(), 'rating':round(float(rating), 3),
            'win_rate':win, 'place_rate':top2,
            'line_id':'', # This upstream feed does not provide verified line IDs.
            'style':style
        })
    return {
        'race_id':'LIVE_'+rid, 'venue':venue.strip(), 'race_no':race_no,
        'class_name':'', 'start_at':start_at.isoformat(timespec='seconds'),
        'captured_at':observed_at, 'source_url':url,
        'entrants':sorted(output,key=lambda x:x['car_no']),
    }


def candidates(raw, day, observed_at=None, *, margin_minutes=30, horizon_hours=12, max_races=3, url='https://example.invalid/entries.json'):
    """Select only not-yet-started races with fully validated pre-race fields."""
    if len(raw) > MAX_PAYLOAD:
        raise ValueError('日次JSONが2MBを超えています')
    try:
        obj = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError('日次JSONを読み込めません: '+str(exc))
    if not isinstance(obj,dict) or not isinstance(obj.get('races'),list):
        raise ValueError('日次JSONにraces配列がありません')
    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',day):
        raise ValueError('dateはYYYY-MM-DD')
    if obj.get('date') not in (day.replace('-',''),day):
        raise ValueError('ファイルの日付と取得対象日が一致しません')
    if not isinstance(margin_minutes,int) or margin_minutes < 0 or not 1 <= max_races <= 10 or not 1 <= horizon_hours <= 48:
        raise ValueError('margin/max_races/horizonが範囲外')
    at = parse_time(observed_at or now_jst())
    if datetime.strptime(day,'%Y-%m-%d').date() < (at-timedelta(days=1)).date():
        raise ValueError('過去の日次ファイルを新しい出走表として扱えません')
    out = []
    dropped = {'already_started_or_soon':0,'beyond_horizon':0,'invalid':0}
    for row in obj['races']:
        try:
            card = _card(row,day,at.isoformat(timespec='seconds'),url)
            start = parse_time(card['start_at'])
            if start <= at + timedelta(minutes=margin_minutes):
                dropped['already_started_or_soon'] += 1
                continue
            if start > at + timedelta(hours=horizon_hours):
                dropped['beyond_horizon'] += 1
                continue
            out.append(card)
        except (TypeError,ValueError,OverflowError):
            dropped['invalid'] += 1
    out.sort(key=lambda x:(x['start_at'],x['race_id']))
    if len({x['race_id'] for x in out}) != len(out):
        raise ValueError('同じrace_idが日次JSON内で重複しています')
    return out[:max_races], {'total':len(obj['races']),'eligible':len(out),'dropped':dropped}


def ingest(con, cards, observed_at=None):
    """Import vetted cards; freeze existing heuristic baseline, never MIRA picks."""
    at = parse_time(observed_at or now_jst()).isoformat(timespec='seconds')
    report = {'created':0,'unchanged':0,'baseline_created':0,'errors':[]}
    for card in cards:
        rid = card['race_id']
        # The source may refresh fields later. Never rewrite a previous frozen racecard.
        if con.execute('SELECT 1 FROM races WHERE id=?',(rid,)).fetchone():
            report['unchanged'] += 1
            # An interrupted prior run might have committed the racecard but not
            # frozen its baseline. Retry once only while it is still pre-start.
            if (con.execute('SELECT 1 FROM real_race_sources WHERE race_id=?',(rid,)).fetchone()
                    and not con.execute('SELECT 1 FROM forecasts WHERE race_id=?',(rid,)).fetchone()):
                try:
                    baseline(con,rid,at=at)
                    report['baseline_created'] += 1
                except (ValueError,TypeError) as exc:
                    report['errors'].append({'race_id':rid,'reason':str(exc)})
            continue
        try:
            status=register_race(con,card,at=at)
            report['created'] += int(status=='created')
            baseline(con,rid,at=at)
            report['baseline_created'] += 1
        except (ValueError,TypeError) as exc:
            report['errors'].append({'race_id':rid,'reason':str(exc)})
    return report


def data_status(con):
    """Small read-only status panel (safe on old DBs without the v0.8 schema)."""
    import html
    from .core import now_jst
    rows=con.execute("""
        SELECT COUNT(*) AS total,
          COUNT(DISTINCT CASE WHEN r.start_at>? THEN r.id END) AS upcoming,
          MAX(s.captured_at) AS last_captured
        FROM races r JOIN real_race_sources s ON s.race_id=r.id
        WHERE r.is_demo=0 AND r.id LIKE 'LIVE_%'
    """,(now_jst(),)).fetchone() if con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_race_sources'"
    ).fetchone() else None
    total=rows['total'] if rows else 0
    upcoming=rows['upcoming'] if rows else 0
    stamp=rows['last_captured'] if rows and rows['last_captured'] else '未取得'
    return ('<section class="panel"><h2>実出走表の取り込み状況</h2>'
            '<p>登録 <b>{}</b>レース ／ 未発走 <b>{}</b>レース ／ 最終取得 <b>{}</b></p>'
            '<p class="muted">外部フィード由来の出走表です。現段階のMIRA自動予想とは異なります。'
            '取得元の利用許可、時点情報、ラインの欠損に注意してください。</p></section>').format(
                total,upcoming,html.escape(str(stamp)))
