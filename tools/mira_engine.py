#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""MIRA rule v1.0: generate auditable top-3 suggestions, freeze, compare."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect
from keirinlab.mira_engine import preview,freeze,paired_scorecard

def main(argv=None):
    p=argparse.ArgumentParser(description='MIRA experimental rule model / 2車単')
    p.add_argument('--db',default=os.getenv('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('preview','freeze'):
        cmd=sub.add_parser(name)
        cmd.add_argument('--race',required=True)
    sub.add_parser('report')
    args=p.parse_args(argv)
    try:
        with connect(args.db,readonly=args.command!='freeze') as con:
            if args.command=='preview':
                d=preview(con,args.race)
                print(json.dumps({k:v for k,v in d.items() if k!='probabilities'},
                                 ensure_ascii=False,indent=2))
            elif args.command=='freeze':
                d=freeze(con,args.race)
                print(json.dumps({k:v for k,v in d.items() if k!='probabilities'},
                                 ensure_ascii=False,indent=2))
                print('実験モデルの確率分布を上書き不可で固定しました。')
            else:
                print(json.dumps(paired_scorecard(con),ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,TypeError) as e:
        print('ERROR:',e,file=sys.stderr)
        return 1

if __name__=='__main__':
    sys.exit(main())
