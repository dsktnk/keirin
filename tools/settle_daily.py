#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""Verify final 2車単 results from a daily JSON. Default is read-only dry run."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError,URLError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect,JST
from keirinlab.resultsfeed import MAX_BYTES,reconcile

def daily_url(day):
    datetime.strptime(day,'%Y-%m-%d')
    return 'https://kurinaka12-afk.github.io/keirin-app-data/'+day+'.json'

def fetch(url):
    req=Request(url,headers={'User-Agent':'KEIRIN-LAB/0.9 (daily-result-verifier)','Accept':'application/json'})
    with urlopen(req,timeout=18) as response:
        if not any(k in response.headers.get('Content-Type','').lower()
                   for k in ('json','text/plain','octet-stream')):
            raise ValueError('結果ファイルはJSONである必要があります')
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError('結果JSONがサイズ上限を超えています')
    return raw

def main(argv=None):
    p=argparse.ArgumentParser(description='MIRA予想・実レース結果の2車単照合')
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--file',type=Path,help='ローカルの同形式結果JSON')
    source.add_argument('--fetch',action='store_true',help='日次結果JSONを一回だけ取得')
    p.add_argument('--date',help='取得日（省略時は今日・日本時間）')
    p.add_argument('--db',default=os.getenv('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    p.add_argument('--source-url',help='ローカルファイルの検証済み取得先')
    p.add_argument('--commit',action='store_true',help='確定結果をSQLiteに保存（省略時はdry-run）')
    p.add_argument('--source-rights-confirmed',action='store_true',help='利用範囲と許諾を確認済み')
    p.add_argument('--no-static',action='store_true')
    args=p.parse_args(argv)
    try:
        day=args.date or datetime.now(JST).date().isoformat()
        url=daily_url(day)
        if args.commit and not args.source_rights_confirmed:
            raise ValueError('保存前に利用条件を確認し --source-rights-confirmed を指定してください')
        if args.fetch and not args.source_rights_confirmed:
            raise ValueError('外部取得前に利用条件を確認してください')
        if args.file and not args.source_url and args.commit:
            raise ValueError('--fileでの保存には --source-url が必要です')
        if args.file:
            raw=args.file.read_bytes()
            source_url=args.source_url or 'https://example.invalid/local-validation'
        else:
            raw=fetch(url)
            source_url=url
        with connect(args.db,readonly=not args.commit) as con:
            result=reconcile(con,raw,day,source_url=source_url,dry_run=not args.commit)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result['settled'] and not args.no_static:
            from build_static import build
            build()
        return 0
    except (ValueError,TypeError,UnicodeError,OSError,URLError,HTTPError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        return 1

if __name__=='__main__':
    sys.exit(main())
