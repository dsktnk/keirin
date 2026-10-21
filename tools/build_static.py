#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""Build self-contained demo/static pages from SQLite without CGI.

Run after changing data:
    /usr/local/bin/python tools/build_static.py
"""
import html
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect
from keirinlab.webapp import render

DB=ROOT/'data'/'keirin_lab.sqlite3'


def static_href(query):
    params={k:v[0] for k,v in parse_qs(html.unescape(query.lstrip('?'))).items()}
    view=params.get('view','dashboard')
    if view=='tipsters':
        w=params.get('window','all')
        return 'tipsters'+('_'+w if w in ('10','30') else '')+'.html'
    if view=='backtest': return 'backtest.html'
    if view=='feed': return 'feed.html'
    if view=='watch': return 'tipstar_watch.html'
    if view=='race':
        rid=params.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',rid):
            return 'index.html'
        return 'race_'+rid+'.html'
    return 'index.html'


def as_static(markup):
    return re.sub(r'href="(\?[^"<>]+)"', lambda m:'href="'+html.escape(static_href(m.group(1)),quote=True)+'"',markup)


def build():
    if not DB.is_file():
        raise SystemExit('データベースがありません: '+str(DB))
    pages={
        'index.html':{},
        'tipsters.html':{'view':'tipsters','window':'all'},
        'tipsters_10.html':{'view':'tipsters','window':'10'},
        'tipsters_30.html':{'view':'tipsters','window':'30'},
        'backtest.html':{'view':'backtest'},
        'feed.html':{'view':'feed'},
        'tipstar_watch.html':{'view':'watch'},
    }
    with connect(DB,readonly=True) as con:
        for (rid,) in con.execute('SELECT id FROM races ORDER BY start_at DESC'):
            if re.fullmatch(r'[A-Za-z0-9_-]{1,128}',rid):
                pages['race_'+rid+'.html']={'view':'race','id':rid}
    for filename,params in pages.items():
        output=as_static(render(DB,params))
        output=output.replace('</main>','<p style="font-size:12px;color:#90a2b9">静的HTML表示。最新のSQLiteデータは <a href="index.cgi">CGI版</a> で確認できます（実行権限755が必要）。</p></main>')
        (ROOT/filename).write_text(output, encoding='utf-8')
    print('生成したHTML:',len(pages),'ページ')


if __name__=='__main__': build()
