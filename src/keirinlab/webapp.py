"""Read-only HTML dashboard, safe to invoke through CGI or dev server."""
import html
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from .core import connect, analyze_race, settled_tipster_stats, backtest, now_jst
from .watch import watch_view
from .research import research_view
from .realrace import mira_panel
from .dailyfeed import data_status
from .mira_engine import panel as mira_engine_panel


def esc(v): return html.escape(str(v),quote=True)
def yen(v): return '{:,.0f}円'.format(v)
def pct(v): return '{:.1f}%'.format(v*100) if v is not None else '—'
def url(**kw): return '?' + urlencode(kw)

CSS = '''
:root{color-scheme:dark;--bg:#090e17;--panel:#131d2b;--line:#26344a;--muted:#90a2b9;--primary:#9ddcf7;--ok:#55d4a7;--bad:#fb9d9c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#ecf3fa;font:15px/1.65 -apple-system,BlinkMacSystemFont,'Hiragino Kaku Gothic ProN',Meiryo,sans-serif}
a{color:var(--primary);text-decoration:none}header{padding:22px max(22px,calc((100vw - 1160px)/2));border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;background:#0d1624}
.logo{font-size:23px;font-weight:800;letter-spacing:.06em;color:white}.logo small{font-size:11px;color:#7db8d8;display:block;font-weight:500;letter-spacing:.14em}nav{display:flex;gap:10px;flex-wrap:wrap}nav a{display:inline-block;padding:9px 14px;border:1px solid var(--line);border-radius:9px;color:#d1dfed}nav a.on{background:#263a53;border-color:#5b799b}
main{max-width:1160px;margin:24px auto;padding:0 20px}.notice{background:#25334a;border:1px solid #45617f;border-radius:12px;padding:12px 16px;margin:16px 0;color:#d2e6fb}.muted{color:var(--muted)}.eyebrow{color:#85b7d7;font-size:11px;letter-spacing:.15em;font-weight:700}h1{font-size:26px;margin:0 0 5px}h2{font-size:19px;margin:0 0 16px}h3{font-size:16px;margin:0}.meta{margin:0 0 22px;color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin-bottom:22px}.stats .tile{border:1px solid var(--line);border-radius:13px;background:var(--panel);padding:15px}.tile strong{display:block;font-size:24px;font-variant-numeric:tabular-nums}.tile span{font-size:12px;color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:19px;margin:17px 0}.columns{display:grid;grid-template-columns:1.3fr 1fr;gap:17px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:510px;font-variant-numeric:tabular-nums}th{text-align:left;color:#a9c0d9;font-size:12px;font-weight:600}td,th{padding:11px 10px;border-bottom:1px solid #29384c}tr:last-child td{border:0}tbody tr:hover{background:#1b2a3d}.tag{font-size:11px;border:1px solid #3c5a7a;border-radius:6px;padding:2px 7px;color:#a9d6ed}.green{color:var(--ok)}.red{color:var(--bad)}.right{text-align:right}.large{font-size:26px;font-weight:750}.race-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.racecard{border-radius:12px;border:1px solid var(--line);padding:15px;background:#172336;display:block;color:#e7f2ff}.racecard:hover{border-color:#82bbda}.racecard b{display:block;font-size:19px}.racecard small{color:#9eb3ca}.footer{color:var(--muted);font-size:12px;padding:20px 0 40px}.split{display:flex;justify-content:space-between;gap:10px;align-items:center}.meter{width:90px;height:6px;border-radius:12px;background:#33475a;display:inline-block;vertical-align:middle;margin-right:6px}.meter i{display:block;height:100%;background:#74cce7;border-radius:12px}
@media(max-width:840px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.race-grid,.columns{grid-template-columns:1fr}}@media(max-width:540px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.tile strong{font-size:19px}h1{font-size:22px}header{padding:18px}}
'''


def shell(body,tab='dashboard',demo=False):
    links=[('dashboard','ダッシュボード'),('feed','取得データ'),('tipsters','予想師分析'),('research','MIRA予測'),('watch','TIPSTAR追跡'),('backtest','バックテスト')]
    nav=''.join('<a class="{}" href="{}">{}</a>'.format('on' if tab==key else '',esc(url(view=key)),label) for key,label in links)
    banner='<div class="notice"><b>DEMO / 架空データ</b>：選手・オッズ・予想師・払戻は検証用の合成データです。実際の競輪予想ではありません。</div>' if demo else ''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KEIRIN LAB v1.0</title><style>'+CSS+'</style></head><body><header><div class="logo">KEIRIN LAB<small>PREDICTION × TIPSTERS × VALIDATION</small></div><nav>'+nav+'</nav></header><main>'+banner+body+'<div class="footer">KEIRIN LAB v1.0 ・分析用。投票機能なし。初期の予測は未学習の統計モデルで、確率の較正・収益性は未検証です。</div></main></body></html>'


def stats_tiles(tiles):
    return '<div class="stats">'+''.join('<div class="tile"><span>{}</span><strong>{}</strong></div>'.format(esc(k),esc(v)) for k,v in tiles)+'</div>'


def dashboard(con):
    races=con.execute('''SELECT r.*, CASE WHEN z.race_id IS NULL THEN 0 ELSE 1 END settled,
                              (SELECT COUNT(*) FROM forecasts f WHERE f.race_id=r.id) forecast_n
                        FROM races r LEFT JOIN results z ON z.race_id=r.id
                        ORDER BY r.start_at DESC LIMIT 50''').fetchall()
    totals=con.execute('''SELECT (SELECT COUNT(*) FROM races) as all_races,
             (SELECT COUNT(DISTINCT race_id) FROM forecasts) as forecast_count,
             (SELECT COUNT(*) FROM results) as settled''').fetchone()
    bt=backtest(con)
    tiles=stats_tiles([('登録レース',totals['all_races']),('予測済み',totals['forecast_count']),('結果確定',totals['settled']),('検証ROI',pct(bt['roi']))])
    out='<div class="eyebrow">OVERVIEW</div><h1>統合分析ダッシュボード</h1><p class="meta">独自予測・予想師・実績を一画面で照合</p>'+tiles
    out+='<div class="panel"><h2>最近のレース一覧（最大50件）</h2><div class="race-grid">'
    for r in races:
        status='結果確定' if r['settled'] else '未確定'
        if not r['forecast_n']: status+=' / 予測未作成'
        out+='<a class="racecard" href="{}"><small>{} ・{}</small><b>{} {}R</b><small>{} / {}</small></a>'.format(
            esc(url(view='race',id=r['id'])),esc(r['race_date']),esc(r['start_at'][11:16]),esc(r['venue']),r['race_no'],esc(r['class_name']),status)
    out+='</div></div>'
    if not races: out+='<p class="notice">レースデータはありません。READMEのCSV取込、またはデモ投入から始めてください。</p>'
    if has_feed(con):
        n=con.execute('SELECT COUNT(*) FROM feed_races').fetchone()[0]
        out+='<div class="notice">取得データとして保存された実レース履歴：<b>{}</b>件。<a href="?view=feed">取得状況を開く →</a></div>'.format(n)
    return out


def has_feed(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feed_races'").fetchone())


def feed_view(con):
    out='<div class="eyebrow">DATA COLLECTION</div><h1>競輪データ取得状況</h1><p class="meta">外部CSVから保存したレース履歴。分析用の出走表・予想データとは分離しています。</p>'
    if not has_feed(con):
        return out+'<div class="notice">取得データはまだありません。サーバーで tools/collect.py を実行してください。</div>'
    stats=con.execute('SELECT (SELECT COUNT(*) FROM feed_races) races,(SELECT COUNT(*) FROM feed_riders) riders,(SELECT COUNT(*) FROM feed_runs) runs').fetchone()
    out+=stats_tiles([('取得レース',stats['races']),('取得選手行',stats['riders']),('取込回数',stats['runs']),('予測利用','未接続')])
    out+='<div class="notice">取得した履歴には、発走前の勝率・連対率・取得時刻がないため、予測やバックテストには自動投入しません。予測結果も生成されません。</div>'
    out+='<section class="panel"><h2>直近の取得履歴</h2><div class="tablewrap"><table><thead><tr><th>取込日時</th><th>出典識別子</th><th class="right">レース</th><th class="right">新規選手行</th><th class="right">更新選手行</th></tr></thead><tbody>'
    for r in con.execute('SELECT fetched_at,source,race_count,new_riders,updated_riders FROM feed_runs ORDER BY id DESC LIMIT 20'):
        out+='<tr><td>{}</td><td>{}</td><td class="right">{}</td><td class="right">{}</td><td class="right">{}</td></tr>'.format(esc(r['fetched_at'][:19]),esc(r['source']),r['race_count'],r['new_riders'],r['updated_riders'])
    out+='</tbody></table></div></section>'
    out+='<section class="panel"><h2>最新の開催日（集計のみ）</h2><div class="tablewrap"><table><thead><tr><th>開催日</th><th>出典識別子</th><th class="right">レース</th><th class="right">出走行</th></tr></thead><tbody>'
    for r in con.execute('''SELECT r.race_date,r.source,COUNT(DISTINCT r.race_id) n,COUNT(e.car_no) riders FROM feed_races r LEFT JOIN feed_riders e ON e.source=r.source AND e.race_id=r.race_id GROUP BY r.race_date,r.source ORDER BY r.race_date DESC LIMIT 30'''):
        out+='<tr><td>{}</td><td>{}</td><td class="right">{}</td><td class="right">{}</td></tr>'.format(esc(r['race_date']),esc(r['source']),r['n'],r['riders'])
    return out+'</tbody></table></div></section>'


def race_view(con,race_id):
    info=analyze_race(con,race_id)
    r=info['race']
    out='<div class="eyebrow">RACE ANALYSIS</div><h1>{} {}R</h1><p class="meta">{} / {} / 発走 {} / スナップショット {}</p>'.format(
        esc(r['venue']),r['race_no'],esc(r['race_date']),esc(r['class_name']),esc(r['start_at'][11:16]),esc(info['asof'] or '未作成'))
    if not info['ranked']:
        return out+'<div class="notice">予測スナップショットがありません。発走前に CLI の snapshot を実行してください。</div>'
    ranks=info['ranked']
    odds_count=sum(x['odds'] is not None for x in ranks)
    out+=stats_tiles([('車立て',len(info['entries'])),('確率モデル','特徴量PL v0.1'),('オッズ取得',str(odds_count)+' / '+str(len(ranks))),('公開予想',len(info['tipsters']))])
    out+='<div class="columns"><section class="panel"><h2>統合スコア上位（買い目候補）</h2><div class="tablewrap"><table><thead><tr><th>2車単</th><th class="right">予測確率</th><th class="right">オッズ</th><th class="right">期待利益率*</th><th class="right">予想師支持</th></tr></thead><tbody>'
    for x in ranks[:15]:
        cls='green' if x['ev'] is not None and x['ev']>0 else 'red'
        ev=pct(x['ev']) if x['ev'] is not None else '—'
        out+='<tr><td><strong>{} → {}</strong></td><td class="right">{}</td><td class="right">{}</td><td class="right {}">{}</td><td class="right">{}（{}件）</td></tr>'.format(
            x['combo'][0],x['combo'][1],pct(x['prob']),('{:.1f}倍'.format(x['odds']) if x['odds'] else '—'),cls,ev,pct(x['support']),x['support_n'])
    out+='</tbody></table></div><p class="muted">* 予測確率×取得時点のオッズ−1。確率未較正のため、実際の優位性や利益を意味しません。統合スコアは相対的モデル確率45%、予想師支持35%、上限を設けた理論EV20%の仮の順位指標です。</p></section>'
    out+='<section class="panel"><h2>出走選手</h2><div class="tablewrap"><table><thead><tr><th>車番・選手</th><th class="right">競走得点</th><th class="right">勝率</th><th class="right">連対率</th><th>ライン</th></tr></thead><tbody>'
    for e in info['entries']:
        out+='<tr><td><b>{}</b> {}</td><td class="right">{:.1f}</td><td class="right">{}</td><td class="right">{}</td><td>{}</td></tr>'.format(e['car_no'],esc(e['rider_name']),e['rating'],pct(e['win_rate']),pct(e['place_rate']),esc(e['line_id']))
    out+='</tbody></table></div></section></div>'
    out+='<section class="panel"><h2>予想師の公開買い目（保存データ）</h2><div class="tablewrap"><table><thead><tr><th>予想師</th><th>組み合わせ</th><th class="right">金額</th><th>記録日時</th></tr></thead><tbody>'
    for p in info['tipsters']:
        out+='<tr><td>{}</td><td>{} → {}</td><td class="right">{}</td><td>{}</td></tr>'.format(esc(p['display_name']),p['combo'][0],p['combo'][1],yen(p['stake_yen']),esc(p['published_at'][5:16]))
    out+='</tbody></table></div>'
    if not info['tipsters']: out+='<p class="muted">発走前に記録された公開予想がありません。</p>'
    out+='</section>'
    res=con.execute('SELECT * FROM results WHERE race_id=?',(race_id,)).fetchone()
    if res: out+='<div class="notice">結果確定：{} → {} → {}（払戻金はバックテストに反映）</div>'.format(res['first_no'],res['second_no'],res['third_no'])
    return out


def tipsters_view(con,window=None):
    stats=sorted(settled_tipster_stats(con,window=window).values(),key=lambda x:(x['n']>=10,x['adjusted_weight'],x['n']),reverse=True)
    out='<div class="eyebrow">TRACK RECORD</div><h1>予想師パフォーマンス</h1><p class="meta">保存した購入予想を、確定済みのレースで集計。払戻実績は保存した買い目に限定。</p>'
    out+='<div class="panel"><span class="muted">評価期間：</span> <a href="?view=tipsters&window=10">直近10レース</a>　/　<a href="?view=tipsters&window=30">直近30レース</a>　/　<a href="?view=tipsters&window=all">全期間</a>　 <span class="tag">選択中：{}</span></div>'.format('全期間' if window is None else '直近{}レース'.format(window))
    out+='<section class="panel"><h2>予想師ランキング（収縮調整値の順）</h2><div class="tablewrap"><table><thead><tr><th>予想師</th><th class="right">レース数</th><th class="right">的中レース率</th><th class="right">回収率</th><th class="right">損益</th><th class="right">調整係数</th></tr></thead><tbody>'
    for t in stats:
        cls='green' if t['net']>=0 else 'red'
        out+='<tr><td>{}</td><td class="right">{}</td><td class="right">{}</td><td class="right">{}</td><td class="right {}">{}</td><td class="right">{:.3f}</td></tr>'.format(
            esc(t['name']),t['n'],pct(t['hit_rate']),pct(t['roi']),cls,('{:+,d}円'.format(t['net'])),t['adjusted_weight'])
    out+='</tbody></table></div><p class="muted">調整係数＝1＋n/(n+30)×(上限3.0倍に丸めた実績ROI−1)、0.65〜1.35へ制限。信頼区間ではなく暫定的な過学習抑制策です。買い目件数と対象レース数は別です。</p></section>'
    return out


def backtest_view(con):
    data=backtest(con)
    out='<div class="eyebrow">OUT OF SAMPLE</div><h1>履歴検証</h1><p class="meta">発走前に凍結した確率・オッズ・買い目を、結果確定後に照合します。</p>'
    out+=stats_tiles([('対象レース',data['races']),('想定投資',yen(data['spent'])),('想定払戻',yen(data['returned'])),('モデル上の回収率',pct(data['roi']))])
    out+='<section class="panel"><h2>同じレース群での3手法比較</h2><div class="tablewrap"><table><thead><tr><th>手法</th><th class="right">対象レース</th><th class="right">的中率</th><th class="right">回収率</th><th class="right">差額</th></tr></thead><tbody>'
    for key,label in [('integrated','統合スコア'),('model','統計モデル単独'),('tipster','予想師支持のみ')]:
        s=data['strategies'][key]
        out+='<tr><td>{}</td><td class="right">{}</td><td class="right">{}</td><td class="right">{}</td><td class="right">{:+,d}円</td></tr>'.format(label,s['races'],pct(s['hit_rate']),pct(s['roi']),s['returned']-s['spent'])
    out+='</tbody></table></div><p class="muted">各方式が1レースあたり100円を仮想投入。予想師支持が存在しない場合、該当レースはその方式のみ除外されます。</p></section>'
    out+='<section class="panel"><h2>1レース100円・統合スコア1位の仮想結果</h2><div class="tablewrap"><table><thead><tr><th>日付</th><th>競輪場</th><th>買い目</th><th class="right">保存時オッズ</th><th class="right">払戻</th><th class="right">差額</th></tr></thead><tbody>'
    for row in reversed(data['rows']):
        out+='<tr><td>{}</td><td>{} {}R</td><td>{} → {}</td><td class="right">{:.1f}倍</td><td class="right">{}</td><td class="right {}">{:+,d}円</td></tr>'.format(esc(row['race']['race_date']),esc(row['race']['venue']),row['race']['race_no'],row['combo'][0],row['combo'][1],row['odds'],yen(row['payout']),'green' if row['net']>0 else 'red',row['net'])
    out+='</tbody></table></div><p class="muted">重要：デモ成績は合成データで実際の市場成績ではありません。欠損オッズのレースは除外。競走得点など特徴量は時点管理したデータのみ利用します。</p></section>'
    return out


def render(db_file, params=None):
    params=params or {}
    view=params.get('view','dashboard')
    if view not in ('dashboard','feed','race','tipsters','research','watch','backtest'): view='dashboard'
    with connect(db_file,readonly=True) as con:
        demo=bool(con.execute('SELECT 1 FROM races WHERE is_demo=1 LIMIT 1').fetchone())
        if view=='race':
            rid=params.get('id','')[:128]
            if not rid: raise ValueError('レースIDが必要です')
            body=race_view(con,rid)
        elif view=='tipsters':
            window={'10':10,'30':30,'all':None}.get(params.get('window','all'))
            body=tipsters_view(con,window=window)
        elif view=='research': body=research_view(con)+data_status(con)+mira_engine_panel(con)+mira_panel(con)
        elif view=='watch': body=watch_view(con)
        elif view=='backtest': body=backtest_view(con)
        elif view=='feed': body=feed_view(con)
        else: body=dashboard(con)
    return shell(body,view,demo)


def main(root_override=None):
    root=Path(root_override) if root_override is not None else Path(os.getenv('KEIRIN_LAB_ROOT',str(Path(__file__).resolve().parents[2])))
    db=os.getenv('KEIRIN_LAB_DB',str(root/'data'/'keirin_lab.sqlite3'))
    method=os.environ.get('REQUEST_METHOD','GET').upper()
    try:
        if method not in ('GET','HEAD'):
            status='405 Method Not Allowed'
            body=shell('<h1>GETまたはHEADのみ対応しています</h1>')
        else:
            qs=parse_qs(os.environ.get('QUERY_STRING','')[:4096],keep_blank_values=True, max_num_fields=20)
            params={k:v[0] for k,v in qs.items()}
            body=render(db,params)
            status='200 OK'
    except Exception as exc:
        # Keep filesystem paths and SQL errors out of HTML responses.
        print('KEIRIN LAB CGI error: {!r}'.format(exc),file=sys.stderr)
        status='503 Service Unavailable'
        body=shell('<h1>データを表示できません</h1><p>データベース・レースID・CGI環境の設定を確認してください。</p>')
    print('Status: '+status)
    print('Content-Type: text/html; charset=utf-8')
    print('Cache-Control: no-store')
    if status.startswith('405'):
        print('Allow: GET, HEAD')
    print('X-Content-Type-Options: nosniff')
    print('Content-Security-Policy: default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'')
    print()
    if method != 'HEAD':
        print(body)
