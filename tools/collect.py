#!/usr/bin/env python3
"""Manually collect authorized CSV (local file or HTTPS GitHub raw URL)."""
import argparse
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect
from keirinlab.feed import read_csv_file,read_csv_url,ingest


def main():
    p=argparse.ArgumentParser(description='KEIRIN LAB v0.4: public race-history CSV importer (operator-only)')
    input=p.add_mutually_exclusive_group(required=True)
    input.add_argument('--file', help='local CSV path')
    input.add_argument('--url', help='explicit HTTPS raw.githubusercontent.com CSV URL')
    p.add_argument('--source', required=True, help='provenance identifier e.g. licensed_feed')
    p.add_argument('--db',default=os.getenv('KEIRIN_LAB_DB',str(ROOT/'data'/'keirin_lab.sqlite3')))
    args=p.parse_args()
    source_ref = args.url or str(Path(args.file).resolve())
    data = read_csv_url(args.url) if args.url else read_csv_file(args.file)
    with connect(args.db) as con:
        r=ingest(con,ROOT,data,source=args.source,source_ref=source_ref)
    print('取込:',r['status'],'レース:',r['races'],'選手行:',r['rows'],
          '新規:',r['new'],'更新:',r['updated'],'同一:',r['same'])
    print('注意: 履歴取得データは予測DBと独立して保存しています。発走前の特徴量ではありません。')

if __name__=='__main__':
    try: main()
    except (ValueError, OSError,UnicodeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)
