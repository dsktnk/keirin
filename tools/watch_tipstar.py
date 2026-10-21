#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""Operator-only CSV entry for TIPSTAR rolling-10 metrics. No scraping."""
import argparse
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from keirinlab.core import connect
from keirinlab.watch import import_observations, watch_stats


def main():
    parser = argparse.ArgumentParser(description='KEIRIN LAB / 予想師ウォッチ（手動・許諾済みCSV）')
    parser.add_argument('--db', default=os.environ.get('KEIRIN_LAB_DB', str(ROOT / 'data' / 'keirin_lab.sqlite3')))
    subs = parser.add_subparsers(dest='action', required=True)
    imp = subs.add_parser('import', help='CSVの観測記録を追加')
    imp.add_argument('--file', required=True)
    subs.add_parser('report', help='保存済み観測件数を表示')
    args = parser.parse_args()
    try:
        if args.action == 'import':
            raw = Path(args.file).read_bytes()
            with connect(args.db) as con:
                info = import_observations(con, raw)
            print('観測記録：新規 {} 件 / 同一 {} 件'.format(info['inserted'], info['unchanged']))
            print('静的HTMLを更新するには tools/build_static.py を実行してください。')
        else:
            with connect(args.db, readonly=True) as con:
                summary = watch_stats(con)
            print('追跡予想師：{} 人 / 観測：{} 件'.format(len(summary), sum(x['n'] for x in summary)))
            for x in summary:
                print('{}: {:.1f}%（観測{}回）'.format(x['name'], x['latest']['roi_10_pct'], x['n']))
    except (ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
