#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect,init_db,import_csv,snapshot,settled_tipster_stats,backtest
from keirinlab.seed import seed_demo

def main():
    parser=argparse.ArgumentParser(description='KEIRIN LAB v0.2 importer & frozen forecasts')
    parser.add_argument('--db',default=os.getenv('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init')
    commands.add_parser('seed-demo')
    imp=commands.add_parser('import-csv')
    imp.add_argument('--kind',required=True,choices=['races','entrants','odds','tipsters','picks','results','payouts'])
    imp.add_argument('--file',required=True)
    shot=commands.add_parser('snapshot')
    shot.add_argument('--race',required=True)
    commands.add_parser('report')
    args=parser.parse_args()
    with connect(args.db) as con:
        if args.command=='init':
            init_db(con,ROOT/'schema.sql');print('Initialized:',args.db)
        elif args.command=='seed-demo':
            init_db(con,ROOT/'schema.sql');print('Seeded synthetic races:',seed_demo(con))
        elif args.command=='import-csv':
            print('Imported rows:',import_csv(con,args.kind,args.file))
        elif args.command=='snapshot':
            print('Frozen ordered pairs:',snapshot(con,args.race))
        elif args.command=='report':
            b=backtest(con)
            print('Backtest:',b['races'],'races; ROI:',b['roi'])
            for t in settled_tipster_stats(con).values():
                print(t['name'],t['n'],'races; ROI:',round(t['roi'],3))
if __name__=='__main__':
    try: main()
    except (ValueError, OSError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
