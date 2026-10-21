"""Pre-race, outcome-blind evaluation for frozen 2車単 forecast distributions.

Python 3.8 compatible; standard library only. Demo and real observations never mix.
This module does not train a model or claim that predictions are calibrated.
"""
import html
import math
from collections import defaultdict
from .core import now_jst, parse_time


def scorecard(con, mode='real', now=None):
    if mode not in ('real', 'demo'):
        raise ValueError('mode は real / demo のみ')
    cutoff = parse_time(now or now_jst())
    flag = 1 if mode == 'demo' else 0
    races = con.execute('''
        SELECT r.id, r.venue, r.start_at, z.first_no, z.second_no, z.finalized_at
        FROM races r JOIN results z ON z.race_id=r.id
        WHERE r.is_demo=? ORDER BY r.start_at, r.id
    ''', (flag,)).fetchall()
    counts = defaultdict(int)
    evaluated = []
    for r in races:
        try:
            start = parse_time(r['start_at'])
            final = parse_time(r['finalized_at'])
        except (TypeError, ValueError):
            counts['invalid_result_time'] += 1
            continue
        if final > cutoff:
            counts['not_finalized'] += 1
            continue
        if final <= start:
            counts['invalid_result_time'] += 1
            continue
        forecasts = con.execute('''
            SELECT combo, probability, model_version, snapshot_at
            FROM forecasts WHERE race_id=? AND bet_type='2車単'
        ''', (r['id'],)).fetchall()
        if not forecasts:
            counts['missing_forecast'] += 1
            continue
        if len({(f['snapshot_at'], f['model_version']) for f in forecasts}) != 1:
            counts['mixed_forecast'] += 1
            continue
        try:
            snap = parse_time(forecasts[0]['snapshot_at'])
        except (TypeError, ValueError):
            counts['invalid_snapshot'] += 1
            continue
        if snap >= start or snap > cutoff:
            counts['invalid_snapshot'] += 1
            continue
        entrants = con.execute(
            'SELECT car_no, captured_at FROM entrants WHERE race_id=?', (r['id'],)
        ).fetchall()
        cars = {str(e['car_no']) for e in entrants}
        expected = {a+b for a in cars for b in cars if a != b}
        if len(cars) < 2 or len(cars) != len(entrants):
            counts['incomplete_entries'] += 1
            continue
        try:
            entries_before = all(parse_time(e['captured_at']) <= snap for e in entrants)
        except (TypeError, ValueError):
            entries_before = False
        if not entries_before:
            counts['late_entries'] += 1
            continue
        prob = {str(f['combo']): float(f['probability']) for f in forecasts}
        if (set(prob) != expected or len(prob) != len(forecasts)
                or not all(math.isfinite(p) and 0 < p <= 1 for p in prob.values())
                or abs(sum(prob.values())-1) > 0.00001):
            counts['invalid_distribution'] += 1
            continue
        winner = str(r['first_no'])+str(r['second_no'])
        if winner not in expected:
            counts['invalid_winner'] += 1
            continue
        rank = sorted(prob, key=lambda key: (-prob[key], key))
        payout = con.execute('''
            SELECT payout_yen_per_100 FROM payouts
            WHERE race_id=? AND bet_type='2車単' AND combo=?
        ''', (r['id'], winner)).fetchone()
        returned = (payout['payout_yen_per_100'] if winner == rank[0] else 0) if payout else None
        evaluated.append({
            'race_id': r['id'], 'venue': r['venue'], 'model': forecasts[0]['model_version'],
            'top1': rank[0], 'winner': winner, 'top1_prob': prob[rank[0]],
            'top1_hit': int(rank[0] == winner), 'top3_hit': int(winner in rank[:3]),
            'logloss': -math.log(prob[winner]),
            'brier': sum((p-(1.0 if combo == winner else 0.0))**2 for combo,p in prob.items()),
            'uniform_chance': 1.0/len(expected), 'returned': returned,
        })
        counts['evaluated'] += 1
    n = len(evaluated)
    paid = [item for item in evaluated if item['returned'] is not None]
    venues = defaultdict(list)
    for item in evaluated:
        venues[item['venue']].append(item)
    by_venue = [{
        'venue': venue, 'n': len(items),
        'top1_hits': sum(x['top1_hit'] for x in items),
        'top1_rate': sum(x['top1_hit'] for x in items)/len(items),
    } for venue, items in venues.items()]
    by_venue.sort(key=lambda x: (-x['n'], x['venue']))
    return {
        'mode': mode, 'evaluated': n, 'counts': dict(counts),
        'top1_hits': sum(x['top1_hit'] for x in evaluated),
        'top3_hits': sum(x['top3_hit'] for x in evaluated),
        'top1_rate': sum(x['top1_hit'] for x in evaluated)/n if n else None,
        'top3_rate': sum(x['top3_hit'] for x in evaluated)/n if n else None,
        'mean_logloss': sum(x['logloss'] for x in evaluated)/n if n else None,
        'mean_brier': sum(x['brier'] for x in evaluated)/n if n else None,
        'uniform_top1_chance': sum(x['uniform_chance'] for x in evaluated)/n if n else None,
        'paid_races': len(paid),
        'roi': sum(x['returned'] for x in paid)/(100*len(paid)) if paid else None,
        'venues': by_venue,
    }


def research_view(con):
    stats = scorecard(con, 'real')
    demo = scorecard(con, 'demo')
    n = stats['evaluated']
    fmt = lambda v: '{:.1f}%'.format(100*v) if v is not None else '—'
    out = ('<div class="eyebrow">MIRA PREDICTION RESEARCH</div>'
           '<h1>MIRA予測・精度検証</h1>'
           '<p class="meta">発走前に固定した確率分布だけを、結果確定後に検証する研究画面。</p>'
           '<div class="notice">現段階は既存の未学習モデルの評価基盤です。'
           'MIRA自身による予想の学習、実データの自動取得、確率の較正は未実装です。'
           '的中や利益を保証するものではありません。</div>')
    out += ('<div class="stats">'
            '<div class="tile"><span>実戦評価レース</span><strong>{}</strong></div>'
            '<div class="tile"><span>2車単1点的中率</span><strong>{}</strong></div>'
            '<div class="tile"><span>上位3点内の的中率</span><strong>{}</strong></div>'
            '<div class="tile"><span>対数損失（小さいほど良）</span><strong>{}</strong></div>'
            '</div>').format(n, fmt(stats['top1_rate']), fmt(stats['top3_rate']),
                             '{:.3f}'.format(stats['mean_logloss']) if n else '—')
    if not n:
        out += ('<section class="panel"><h2>実戦データの検証はまだ0件</h2>'
                '<p>架空データは実戦成績に混ぜません。実レースの発走前データ・'
                '凍結予測・確定結果が揃うと、自動的に検証できます。</p></section>')
    else:
        out += ('<section class="panel"><h2>確率と買い目の評価</h2>'
                '<p>単純な一様確率で1点を選ぶ場合の理論的中率：<b>{}</b>。'
                '平均Brierスコア：<b>{:.3f}</b>（小さいほど良）。'
                '払戻の照合可能なレース：<b>{}</b>件、仮想100円1点購入の回収率：<b>{}</b>。</p>'
                '<p class="muted">Brierは全2車単組み合わせの確率誤差の合計。'
                '欠損オッズ・払戻を的中率の失敗として扱いません。'
                '少数サンプルの優位性は確認できません。</p></section>').format(
                    fmt(stats['uniform_top1_chance']), stats['mean_brier'],
                    stats['paid_races'], fmt(stats['roi']))
        out += ('<section class="panel"><h2>競輪場別の弱点（少数標本に注意）</h2>'
                '<div class="tablewrap"><table><thead><tr><th>競輪場</th>'
                '<th class="right">評価件数</th><th class="right">1点的中</th>'
                '<th class="right">1点的中率</th></tr></thead><tbody>')
        for item in stats['venues']:
            out += '<tr><td>{}</td><td class="right">{}</td><td class="right">{}</td><td class="right">{}</td></tr>'.format(
                html.escape(str(item['venue']), quote=True), item['n'],
                item['top1_hits'], fmt(item['top1_rate']))
        out += '</tbody></table></div></section>'
    out += ('<section class="panel"><h2>研究データの品質</h2>'
            '<p>予測が存在しないレースや発走後の情報を含むレースは、精度計算から除外します。</p>'
            '<p class="muted">検証可能な架空レース：{}件（動作確認専用。実戦結果には算入しません）。</p>'
            '</section>').format(demo['evaluated'])
    return out
