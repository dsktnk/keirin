"""External race history ingestion (Python 3.8+, standard library only).

This is a separate STAGING area, not forecast input. In particular, this format
has no reliable pre-race start_at, win_rate, place_rate, or timestamped odds.
"""
import csv
import hashlib
import io
import ipaddress
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from .core import now_jst

MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_ROWS = 160000
EXPECTED = ('race_id', 'venue_slug', 'date', 'race_no', 'banum', 'player_name')
OPTIONAL = ('race_score','rank','lineup','payout','player_class','running_style',
            'pref','age','term')


def setup(con, root):
    con.executescript((Path(root) / 'feed_schema.sql').read_text(encoding='utf-8'))
    con.commit()


def _not_local_https(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port:
        raise ValueError('URLは認証情報を含まないHTTPSアドレスで指定してください')
    if len(url) > 2048 or u.hostname.lower() in ('localhost',) or u.hostname.endswith('.local'):
        raise ValueError('ローカルアドレスは取得できません')
    try:
        ipaddress.ip_address(u.hostname)
        raise ValueError('IPアドレス直指定はできません')
    except ValueError as e:
        if '直指定' in str(e):
            raise
    # Only explicitly supported public CSV host. Redirects are prohibited.
    if u.hostname.lower() != 'raw.githubusercontent.com':
        raise ValueError('URL取得は raw.githubusercontent.com のみ対応。その他はファイルをダウンロードして --file で読み込んでください')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('リダイレクトを伴う取得には対応しません')


def read_csv_url(url, timeout=20):
    """Fetch a public CSV by operator-triggered CLI; no CGI network access."""
    _not_local_https(url)
    req = urllib.request.Request(url, headers={'User-Agent':'KEIRIN-LAB/0.4 (manual importer)', 'Accept':'text/csv,text/plain'})
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=timeout) as resp:
        if resp.status != 200:
            raise ValueError('HTTP ' + str(resp.status))
        declared = resp.headers.get('Content-Length')
        if declared and int(declared) > MAX_DOWNLOAD:
            raise ValueError('CSVがサイズ上限を超えています')
        data = resp.read(MAX_DOWNLOAD+1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('CSVがサイズ上限を超えています')
    return data


def read_csv_file(path):
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError('ファイルが見つかりません: ' + str(p))
    if p.stat().st_size > MAX_DOWNLOAD:
        raise ValueError('CSVがサイズ上限を超えています')
    return p.read_bytes()


def _text(value):
    return str(value or '').strip()


def _int(value, what, lo, hi, nullable=False):
    s = _text(value)
    if nullable and not s:
        return None
    try:
        v = int(s)
    except (TypeError, ValueError):
        raise ValueError('{} は整数で指定: {}'.format(what,s))
    if not lo <= v <= hi:
        raise ValueError('{} が範囲外: {}'.format(what,s))
    return v


def _score(value):
    s = _text(value)
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        raise ValueError('race_scoreは数値で指定')
    if not 0 <= v <= 150 or v != v:
        raise ValueError('race_scoreが範囲外')
    return v


def parse_csv_bytes(data):
    """All rows validated before writing so malformed downloads change nothing."""
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('CSVがサイズ上限を超えています')
    try:
        decoded = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('UTF-8 CSVだけに対応しています')
    rd = csv.DictReader(io.StringIO(decoded,newline=''))
    if not rd.fieldnames or not set(EXPECTED).issubset(set(rd.fieldnames)):
        raise ValueError('必要列: ' + ', '.join(EXPECTED))
    out = []
    race_metadata = {}
    keys = set()
    for line,row in enumerate(rd,2):
        if line > MAX_ROWS+1:
            raise ValueError('行数上限を超えています')
        if None in row:  # unexpected extra columns
            raise ValueError('{}行目: 列数が一致しません'.format(line))
        rid = _text(row['race_id'])
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',rid):
            raise ValueError('{}行目: race_idの形式が不正'.format(line))
        raw_date = _text(row['date'])
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError('{}行目: dateはYYYY-MM-DD'.format(line))
        if day.isoformat() != raw_date:
            raise ValueError('{}行目: dateはYYYY-MM-DD'.format(line))
        venue = _text(row['venue_slug'])
        if not venue or len(venue)>90:
            raise ValueError('{}行目: venue_slugが不正'.format(line))
        race_no = _int(row['race_no'],'race_no',1,12)
        car = _int(row['banum'],'banum',1,9)
        name = _text(row['player_name'])
        if not name or len(name) > 120:
            raise ValueError('{}行目: 選手名が不正'.format(line))
        meta = (raw_date, venue, race_no)
        if rid in race_metadata and race_metadata[rid] != meta:
            raise ValueError('{}行目: 同一race_idの開催情報が不一致'.format(line))
        race_metadata[rid] = meta
        key = (rid,car)
        if key in keys:
            raise ValueError('{}行目: race_idと車番が重複'.format(line))
        keys.add(key)
        opt = lambda k: _text(row.get(k,''))
        out.append((rid,car,name,_score(opt('race_score')),
                    opt('player_class')[:40],opt('running_style')[:20],
                    _int(opt('rank'),'rank',1,9,nullable=True),
                    opt('lineup')[:500],opt('payout')[:500],
                    opt('pref')[:80], _int(opt('age'),'age',16,110,nullable=True),
                    opt('term')[:40]))
    if not out:
        raise ValueError('CSVに有効な行がありません')
    return race_metadata,out


def ingest(con, root, data, *, source, source_ref):
    """Idempotent INSERT/UPDATE; never remove absent rows from previous runs."""
    if not re.fullmatch('[A-Za-z0-9_-]{1,50}', source):
        raise ValueError('sourceは英数字・_・- で指定してください')
    races, riders = parse_csv_bytes(data) # no modification until validate success
    setup(con,root)
    digest = hashlib.sha256(data).hexdigest()
    if con.execute('SELECT 1 FROM feed_runs WHERE source=? AND source_sha256=?',
                   (source,digest)).fetchone():
        return {'status':'unchanged','races':len(races),'rows':len(riders),'new':0,'updated':0,'same':len(riders)}
    at = now_jst()
    new = updated = same = 0
    with con:
        for rid,(day,venue,race_no) in races.items():
            old = con.execute('SELECT race_date,venue,race_no FROM feed_races WHERE source=? AND race_id=?',
                              (source,rid)).fetchone()
            if old and tuple(old) != (day,venue,race_no):
                raise ValueError('既存のレース開催情報と不一致: ' + rid)
            if old:
                con.execute('UPDATE feed_races SET last_seen_at=? WHERE source=? AND race_id=?',(at,source,rid))
            else:
                con.execute('INSERT INTO feed_races VALUES (?,?,?,?,?,?,?)',(source,rid,day,venue,race_no,at,at))
        for rider in riders:
            rid,car = rider[0],rider[1]
            existing=con.execute('''SELECT player_name,race_score,rider_class,running_style,rank,lineup,payout_raw,pref,age,term
                                     FROM feed_riders WHERE source=? AND race_id=? AND car_no=?''',(source,rid,car)).fetchone()
            fields=rider[2:]
            if existing is None:
                new += 1
                con.execute('''INSERT INTO feed_riders (source,race_id,car_no,player_name,race_score,rider_class,running_style,rank,lineup,payout_raw,pref,age,term,updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(source,)+rider+(at,))
            elif tuple(existing)!=fields:
                updated += 1
                con.execute('''UPDATE feed_riders SET player_name=?,race_score=?,rider_class=?,running_style=?,rank=?,lineup=?,payout_raw=?,pref=?,age=?,term=?,updated_at=?
                               WHERE source=? AND race_id=? AND car_no=?''',fields+(at,source,rid,car))
            else:
                same += 1
        con.execute('''INSERT INTO feed_runs(source,source_ref,source_sha256,fetched_at,file_rows,race_count,new_riders,updated_riders,unchanged_riders)
                       VALUES (?,?,?,?,?,?,?,?,?)''',(source,source_ref[:512],digest,at,len(riders),len(races),new,updated,same))
    return {'status':'imported','races':len(races),'rows':len(riders),'new':new,'updated':updated,'same':same}
