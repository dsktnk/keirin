"""Operator-entered TIPSTAR metric observations; no TIPSTAR network/login access.

TIPSTAR's published ROI is a rolling last-10-predictions value. Observations
are overlapping snapshots, never independent bets or independently observed ROI.
"""
import csv
import html
import io
import math
import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlsplit

from .core import canonical_time, now_jst, parse_time

REQUIRED = ('tipster_id', 'display_name', 'observed_at', 'roi_10_pct')
OPTIONAL = ('popularity', 'contribution_note', 'source_url')
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

SCHEMA = '''
CREATE TABLE IF NOT EXISTS watch_snapshots (
    tipster_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    display_name TEXT NOT NULL,
    roi_10_pct REAL NOT NULL CHECK(roi_10_pct BETWEEN 0 AND 10000),
    popularity INTEGER CHECK(popularity IS NULL OR popularity >= 0),
    contribution_note TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(tipster_id, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_watch_snapshots_time ON watch_snapshots(observed_at DESC);
'''


def table_exists(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='watch_snapshots'").fetchone() is not None


def _source_url(s):
    if not s:
        return ''
    if len(s) > 1024 or '\\' in s or any(ord(c) < 32 for c in s):
        raise ValueError('source_url が不正です')
    u = urlsplit(s)
    if u.scheme != 'https' or u.hostname not in ('tipstar.com', 'www.tipstar.com') or u.username or u.password or u.port not in (None, 443):
        raise ValueError('source_url は https://tipstar.com/ のURLのみ指定可能です')
    return s


def parse_observations(raw):
    """Validate the entire CSV before making any DB changes."""
    if len(raw) > MAX_BYTES:
        raise ValueError('CSVが2MBを超えています')
    try:
        decoded = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('CSVはUTF-8で保存してください')
    reader = csv.DictReader(io.StringIO(decoded, newline=''))
    if not reader.fieldnames or any(k not in reader.fieldnames for k in REQUIRED):
        raise ValueError('必須ヘッダー: ' + ','.join(REQUIRED))
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('ヘッダー名が重複しています')
    rows = []
    seen = set()
    for line, data in enumerate(reader, 2):
        if len(rows) >= MAX_ROWS:
            raise ValueError('5000行まで対応しています')
        if None in data:
            raise ValueError('{}行目: 余分な列があります'.format(line))
        identifier = (data.get('tipster_id') or '').strip()
        name = (data.get('display_name') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identifier):
            raise ValueError('{}行目: tipster_id は英数字・_・- のみ'.format(line))
        if not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('{}行目: 表示名が不正です'.format(line))
        try:
            at = canonical_time((data.get('observed_at') or '').strip())
            if parse_time(at) > parse_time(now_jst()):
                raise ValueError('未来の観測日時は登録できません')
            roi = float((data.get('roi_10_pct') or '').strip())
            if not math.isfinite(roi) or not (0 <= roi <= 10000):
                raise ValueError('回収率は0〜10000%')
            popularity_raw = (data.get('popularity') or '').strip()
            popularity = int(popularity_raw) if popularity_raw else None
            if popularity is not None and not 0 <= popularity <= 100000000:
                raise ValueError('人気の値が範囲外です')
            note = (data.get('contribution_note') or '').strip()
            if len(note) > 120 or any(ord(c) < 32 for c in note):
                raise ValueError('貢献実績メモが不正です')
            link = _source_url((data.get('source_url') or '').strip())
        except (ValueError, OverflowError) as exc:
            raise ValueError('{}行目: {}'.format(line, exc))
        key = (identifier, at)
        if key in seen:
            raise ValueError('{}行目: 同じ予想師・観測日時が重複'.format(line))
        seen.add(key)
        rows.append((identifier, at, name, roi, popularity, note, link))
    if not rows:
        raise ValueError('観測値がありません')
    return rows


def import_observations(con, raw):
    rows = parse_observations(raw)
    con.executescript(SCHEMA)
    inserted = unchanged = 0
    with con:
        for record in rows:
            old = con.execute('''SELECT tipster_id,observed_at,display_name,roi_10_pct,popularity,
                               contribution_note,source_url FROM watch_snapshots
                               WHERE tipster_id=? AND observed_at=?''', record[:2]).fetchone()
            if old:
                if tuple(old) != record:
                    raise ValueError('登録済みの観測日時を上書きできません: {} {}'.format(*record[:2]))
                unchanged += 1
            else:
                con.execute('''INSERT INTO watch_snapshots
                             (tipster_id,observed_at,display_name,roi_10_pct,popularity,contribution_note,source_url)
                             VALUES (?,?,?,?,?,?,?)''', record)
                inserted += 1
    return {'inserted': inserted, 'unchanged': unchanged, 'total': len(rows)}


def watch_stats(con):
    if not table_exists(con):
        return []
    rows = con.execute('''SELECT * FROM watch_snapshots ORDER BY tipster_id,observed_at''').fetchall()
    groups = defaultdict(list)
    for row in rows:
        groups[row['tipster_id']].append(dict(row))
    result = []
    for identifier, history in groups.items():
        latest = history[-1]
        previous = history[-2] if len(history) > 1 else None
        result.append({'id': identifier, 'name': latest['display_name'], 'n': len(history),
                       'latest': latest, 'previous': previous,
                       'delta': latest['roi_10_pct'] - previous['roi_10_pct'] if previous else None,
                       'history': history[-12:]})
    return sorted(result, key=lambda x: (x['n'] >= 3, x['latest']['roi_10_pct']), reverse=True)


def _esc(text):
    return html.escape(str(text), quote=True)


def _sparkline(points):
    if len(points) < 2:
        return '<span class="muted">観測待ち</span>'
    vals = [float(p['roi_10_pct']) for p in points]
    lo, hi = min(vals), max(vals)
    denom = (hi - lo) if hi != lo else 1.0
    coords = ' '.join('{:.0f},{:.0f}'.format(i * 100 / (len(vals) - 1), 35 - (v - lo) / denom * 30) for i, v in enumerate(vals))
    return '<svg width="120" height="40" viewBox="0 0 100 40" role="img" aria-label="保存された回収率の推移"><polyline points="{}" fill="none" stroke="#9ddcf7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'.format(coords)


def watch_view(con):
    stats = watch_stats(con)
    count = sum(row['n'] for row in stats)
    out = ('<div class="eyebrow">TIPSTAR WATCH / MANUAL OBSERVATIONS</div>'
           '<h1>予想師ウォッチ</h1>'
           '<p class="meta">直近10件の公開予想に基づく表示回収率を、観測日時ごとに記録して変化を見る分析ページ。</p>'
           '<div class="notice">TIPSTARとは未連携。データは許諾を確認して運営者が手動登録した観測値のみ。'
           '同じ10件が重なるため、観測数は予想数でも的中数でもありません。ランキングは参考値で利益を保証しません。</div>')
    out += ('<div class="stats"><div class="tile"><span>追跡予想師</span><strong>{}</strong></div>'
            '<div class="tile"><span>観測記録</span><strong>{}</strong></div>'
            '<div class="tile"><span>推移を比較できる予想師</span><strong>{}</strong></div>'
            '<div class="tile"><span>データ取得方式</span><strong>手動CSV</strong></div></div>').format(len(stats), count, sum(s['n'] > 1 for s in stats))
    if not stats:
        return out + ('<section class="panel"><h2>まだ観測データがありません</h2>'
                      '<p>許諾済みの情報を <code>tools/watch_tipstar.py import --file ファイル.csv</code> から登録できます。'
                      'CSV形式は <code>docs/TIPSTAR_WATCH.md</code> を参照してください。</p></section>')
    out += ('<section class="panel"><h2>追跡一覧（3回以上の観測を優先）</h2>'
            '<div class="tablewrap"><table><thead><tr><th>予想師</th><th>最新観測</th><th class="right">表示回収率</th>'
            '<th class="right">前回との差</th><th>推移</th><th class="right">観測数</th><th>参照先</th></tr></thead><tbody>')
    for row in stats:
        r = row['latest']
        difference = row['delta']
        out += ('<tr><td><strong>{}</strong><br><span class="muted">{}</span></td><td>{}</td>'
                '<td class="right">{:.1f}%</td><td class="right {}">{}</td><td>{}</td>'
                '<td class="right">{}</td><td>{}</td></tr>').format(
                    _esc(row['name']), _esc(row['id']), _esc(r['observed_at'][:16].replace('T', ' ')),
                    r['roi_10_pct'], 'green' if difference is not None and difference > 0 else 'muted',
                    '{:+.1f}pt'.format(difference) if difference is not None else '—',
                    _sparkline(row['history']), row['n'],
                    '<a href="{}" target="_blank" rel="noopener noreferrer">TIPSTAR ↗</a>'.format(_esc(r['source_url'])) if r['source_url'] else '—')
    out += '</tbody></table></div><p class="muted">変化は前回との差（ポイント）。推移グラフは直近12回の観測値で、横軸は等間隔の観測順です。人気・貢献実績はCSVに保存しますが、まだ統合スコアへ加算しません。</p></section>'
    return out
