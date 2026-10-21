"""Strict cross-source result reconciliation for real pre-start keirin races.

Accepts the documented JSON shape used by an external daily archive, but no
source is automatically trusted. Strictly verify identity and payout; never
infer results or persist incomplete/tied finishes.
"""
import json
import re
from datetime import datetime
from .core import now_jst,parse_time
from .realrace import settle_race

MAX_BYTES=4*1024*1024
RID=re.compile(r'\d{12}\Z')
DAY=re.compile(r'20\d{2}-\d{2}-\d{2}\Z')

def parse_result_feed(raw, day):
    if len(raw)>MAX_BYTES: raise ValueError('結果JSONが4MBを超えています')
    if not DAY.fullmatch(day): raise ValueError('dateはYYYY-MM-DD')
    datetime.strptime(day,'%Y-%m-%d')
    try:
        obj=json.loads(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError) as e:
        raise ValueError('結果JSONが不正: '+str(e))
    if not isinstance(obj,dict) or obj.get('date') not in (day,day.replace('-','')):
        raise ValueError('結果JSONの対象日が異なります')
    races=obj.get('races')
    if not isinstance(races,list) or len(races)>300:
        raise ValueError('結果JSONのレース配列が不正')
    result={}
    for item in races:
        if not isinstance(item,dict): continue
        rid=item.get('race_id')
        if not isinstance(rid,str) or not RID.fullmatch(rid): continue
        if rid in result: raise ValueError('race_idが重複: '+rid)
        result[rid]=item
    return result

def verified_settlement(con, row, day):
    """Return (settlement dict, reason). Reject missing, ambiguous, malformed."""
    rid=row['race_id']
    source_id=rid.removeprefix('LIVE_') if hasattr(rid,'removeprefix') else rid[5:]
    if not RID.fullmatch(source_id) or not source_id.startswith(day.replace('-','')):
        return None,'race_id/date mismatch'
    if row['race_date']!=day: return None,'race date mismatch'
    venue_row=row['venue']
    record=row['record']
    if record.get('venue')!=venue_row or record.get('race_number')!=row['race_no']:
        return None,'venue or race number mismatch'
    top=record.get('result_top3')
    if not isinstance(top,list) or len(top)!=3 or any(type(x) is not int or not 1<=x<=9 for x in top) or len(set(top))!=3:
        return None,'result pending or ambiguous'
    cars={x[0] for x in con.execute('SELECT car_no FROM entrants WHERE race_id=?',(rid,))}
    n=record.get('n_cars')
    if not cars or not set(top).issubset(cars) or (type(n) is int and n!=len(cars)):
        return None,'entrant mismatch'
    if record.get('result_places') and (not isinstance(record['result_places'],list) or any(not isinstance(p,list) or len(p)!=1 for p in record['result_places'][:3])):
        return None,'tied finish'
    payouts=record.get('payouts')
    if not isinstance(payouts,dict): return None,'missing payouts'
    exacta=payouts.get('exacta')
    if not isinstance(exacta,list) or len(exacta)!=1: return None,'ambiguous 2車単 payouts'
    pay=exacta[0]
    if not isinstance(pay,dict) or pay.get('combo')!=top[:2] or type(pay.get('payout')) is not int or not 100<=pay['payout']<=100000000:
        return None,'2車単 payout mismatch'
    return {'race_id':rid,'first_no':top[0],'second_no':top[1],
            'third_no':top[2],'payout_yen_per_100':pay['payout']},None

def reconcile(con, raw, day, *, source_url, at=None, dry_run=True):
    """Read-only by default. Independently imported pre-start racecard required."""
    from .realrace import source_url as check_url
    source_url=check_url(source_url)
    parsed=parse_result_feed(raw,day)
    now=parse_time(at or now_jst())
    tracked=con.execute("""
        SELECT r.id,r.venue,r.race_no,r.race_date,r.start_at
        FROM races r JOIN real_race_sources s ON s.race_id=r.id
        WHERE r.is_demo=0 AND r.race_date=? ORDER BY r.start_at,r.id
    """,(day,)).fetchall() if con.execute(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_race_sources'"
    ).fetchone() else []
    report={'tracked':len(tracked),'available':len(parsed),'settled':0,'eligible':0,
            'already':0,'skipped':[],'dry_run':dry_run}
    for race in tracked:
        rid=race['id']
        record=parsed.get(rid[5:] if rid.startswith('LIVE_') else rid)
        if record is None:
            report['skipped'].append((rid,'missing in result feed'));continue
        if now<=parse_time(race['start_at']):
            report['skipped'].append((rid,'race has not started'));continue
        if con.execute('SELECT 1 FROM results WHERE race_id=?',(rid,)).fetchone():
            report['already']+=1;continue
        item=dict(race);item['race_id']=rid;item['record']=record
        settlement,reason=verified_settlement(con,item,day)
        if reason:
            report['skipped'].append((rid,reason));continue
        report['eligible']+=1
        if not dry_run:
            try:
                settle_race(con,dict(settlement,source_url=source_url),at=now.isoformat(timespec='seconds'))
                report['settled']+=1
            except (ValueError,TypeError) as exc:
                report['skipped'].append((rid,str(exc)))
    return report
