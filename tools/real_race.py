#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""KEIRIN LAB v0.7 operator-only real race pipeline (no network access)."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect, init_db
from keirinlab.realrace import register_race, baseline, predict_mira, settle_race, mira_summary


def load_json(file):
    raw = Path(file).read_bytes()
    if len(raw) > 100000:
        raise ValueError('JSONが100KBを超えています')
    def pairs(data):
        result = {}
        for k,v in data:
            if k in result:
                raise ValueError('JSONキーが重複: '+k)
            result[k] = v
        return result
    return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs)


def main():
    p=argparse.ArgumentParser(description='実レース → 比較モデル → MIRA予想 → 結果検証')
    p.add_argument('--db',default=os.environ.get('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    commands=p.add_subparsers(dest='command',required=True)
    for command in ('register','predict','settle'):
        parser=commands.add_parser(command)
        parser.add_argument('--file',required=True)
    b=commands.add_parser('baseline')
    b.add_argument('--race',required=True)
    commands.add_parser('report')
    args=p.parse_args()
    try:
        with connect(args.db) as con:
            init_db(con,ROOT/'schema.sql')
            if args.command=='register':
                print('出走表:',register_race(con,load_json(args.file)))
            elif args.command=='baseline':
                print('2車単の比較確率を固定:',baseline(con,args.race),'点')
            elif args.command=='predict':
                print('MIRA予想固定:',predict_mira(con,load_json(args.file)))
            elif args.command=='settle':
                print('確定結果:',settle_race(con,load_json(args.file)))
            else:
                stats=mira_summary(con)
                print('MIRA記録 {} 件 / 結果確定 {} 件 / 本命的中 {} 件 / 回収率 {}'.format(
                    stats['total'],stats['settled'],stats['hits'],
                    '{:.1f}%'.format(stats['roi']*100) if stats['roi'] is not None else '—'))
                for x in stats['entries'][:20]:
                    print(x['date'],x['venue'],str(x['race_no'])+'R',x['best'],x['status'])
    except (ValueError,TypeError,OSError,UnicodeError,json.JSONDecodeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
