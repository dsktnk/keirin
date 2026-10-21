#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""Low-frequency daily JSON intake. Not a TIPSTAR scraper and not auto-deployed.

External source may be viewed publicly but publication is not a reuse license.
Use --source-rights-confirmed only after verifying permission for your use.
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from keirinlab.core import JST, connect, init_db, now_jst
from keirinlab.dailyfeed import MAX_PAYLOAD, candidates, ingest

GITHUB_HOST = 'raw.githubusercontent.com'
INTERVAL = 3600
LIMIT = MAX_PAYLOAD


def daily_url(day):
    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',day):
        raise ValueError('対象日はYYYY-MM-DDで指定してください')
    datetime.strptime(day,'%Y-%m-%d')
    return 'https://raw.githubusercontent.com/snarfnet/keirin-data/main/entries_'+day.replace('-','')+'.json'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Avoid silently sending requests to other hosts.
        if urlsplit(newurl).hostname != GITHUB_HOST or urlsplit(newurl).scheme != 'https':
            raise ValueError('予期しないリダイレクトを拒否しました')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def retrieve(url, marker, opener=None, clock=time.time):
    opener = opener or build_opener(NoRedirect())
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open('a+',encoding='ascii') as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        f.seek(0)
        try: last=float(f.read().strip() or '0')
        except ValueError: last=0
        current=clock()
        if current-last < INTERVAL:
            raise ValueError('取得間隔を空けてください（残り{}秒）'.format(int(INTERVAL-(current-last))+1))
        f.seek(0)
        f.truncate()
        f.write(str(current))
        f.flush()
        req=Request(url,headers={'User-Agent':'KEIRIN-LAB/0.8 (research/one-daily-feed)','Accept':'application/json'})
        with opener.open(req,timeout=15) as resp:
            content_type=resp.headers.get('Content-Type','').lower()
            if 'json' not in content_type and 'octet-stream' not in content_type and 'text/plain' not in content_type:
                raise ValueError('JSONではないContent-Type: '+content_type[:80])
            data=resp.read(LIMIT+1)
        if len(data)>LIMIT:
            raise ValueError('取得ファイルが2MBを超えました')
        return data


def main(argv=None):
    p=argparse.ArgumentParser(description='実レース出走表JSON取り込み・凍結ベースライン（低頻度）')
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--fetch-today',action='store_true',help='公開GitHub日次JSONを1回だけ取得')
    source.add_argument('--file',type=Path,help='手元の同形式JSONを読み込む（ネットワークなし）')
    p.add_argument('--date',help='出走表の日付。省略時は日本の今日')
    p.add_argument('--source-url',help='--file利用時に保存する実際の原データ取得元HTTPS URL')
    p.add_argument('--db',default=os.getenv('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    p.add_argument('--max-races',type=int,default=3,help='発走前レース最大件数（1〜10）')
    p.add_argument('--margin-minutes',type=int,default=30,help='発走までの最低残り時間')
    p.add_argument('--dry-run',action='store_true',help='保存・ページ更新せず抽出結果を表示')
    p.add_argument('--source-rights-confirmed',action='store_true',help='利用範囲と原データの権利を確認した')
    p.add_argument('--no-static',action='store_true',help='静的HTMLの再生成を行わない')
    args=p.parse_args(argv)
    try:
        day=args.date or datetime.now(JST).date().isoformat()
        url=daily_url(day)
        # Reading and repeated copying from public GitHub is not automatically authorized.
        if (args.fetch_today or not args.dry_run) and not args.source_rights_confirmed:
            raise ValueError('利用条件を確認のうえ --source-rights-confirmed を指定してください')
        if args.file and not args.dry_run and not args.source_url:
            raise ValueError('--fileで実データを保存する場合は --source-url が必要です')
        if args.fetch_today and args.source_url:
            raise ValueError('--fetch-todayでは取得元URLを変更できません')
        if args.max_races<1 or args.max_races>10 or args.margin_minutes<0 or args.margin_minutes>180:
            raise ValueError('max-races/margin-minutesが範囲外です')
        if args.file:
            raw=args.file.read_bytes()
            ref=str(args.file.resolve())
        else:
            raw=retrieve(url,ROOT/'data'/'.dailyfeed_last_fetch')
            ref=url
        observed=now_jst()
        # Never publish a local filesystem path as the asserted data provenance.
        source_ref=(args.source_url or 'https://example.invalid/dry-run') if args.file else url
        cards,metrics=candidates(raw,day,observed_at=observed,
                                 margin_minutes=args.margin_minutes,
                                 max_races=args.max_races,url=source_ref)
        print('取得先:',ref)
        print('日次レース:',metrics['total'],'条件適合:',metrics['eligible'],
              '今回候補:',len(cards),'除外:',metrics['dropped'])
        for card in cards:
            print(card['race_id'],card['venue'],str(card['race_no'])+'R',
                  card['start_at'][11:16],'車立て',len(card['entrants']))
        if args.dry_run:
            print('検証モード: データベースへの書き込みなし')
            return 0
        if not cards:
            print('発走前の条件適合レースがありません。保存せず終了。')
            return 0
        with connect(args.db) as con:
            init_db(con,ROOT/'schema.sql')
            report=ingest(con,cards,observed)
        print('登録:',report['created'],'既存:',report['unchanged'],
              '比較予測を固定:',report['baseline_created'],
              'MIRAルール予測を固定:',report['mira_rule_created'],'エラー:',len(report['errors']))
        for error in report['errors']:
            print('SKIPPED:',error['race_id'],error['reason'],file=sys.stderr)
        if report['created'] and not args.no_static:
            # One local rebuild; no extra network requests.
            from build_static import build
            build()
        return 1 if report['errors'] else 0
    except (OSError,URLError,HTTPError,ValueError,UnicodeError) as error:
        print('ERROR:',error,file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
