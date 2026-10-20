import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import (connect,init_db,compute_probabilities, snapshot,
                             analyze_race,settled_tipster_stats,import_csv,parse_time,backtest)
from keirinlab.seed import seed_demo
from keirinlab.webapp import render

class KeirinLabTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=Path(self.folder.name)/'test.sqlite3'
        self.con=connect(self.db)
        init_db(self.con,ROOT/'schema.sql')
    def tearDown(self):
        self.con.close();self.folder.cleanup()
    def seed(self):
        seed_demo(self.con)
    def test_probabilities_sum_to_one(self):
        self.seed()
        es=self.con.execute('SELECT * FROM entrants WHERE race_id=?',('DEMO_20261010_08',)).fetchall()
        p=compute_probabilities(es)
        self.assertEqual(len(p),42)
        self.assertAlmostEqual(sum(p.values()),1,places=12)
        self.assertTrue(all(0<v<1 for v in p.values()))
    def test_forecasts_are_immutable(self):
        self.seed()
        with self.assertRaisesRegex(ValueError,'上書きは禁止'):
            snapshot(self.con,'DEMO_20261010_08','2026-10-10T16:50:00+09:00')
    def test_tipster_windows(self):
        self.seed()
        a=settled_tipster_stats(self.con)
        ten=settled_tipster_stats(self.con,window=10)
        self.assertTrue(max(x['n'] for x in ten.values())<=10)
        self.assertTrue(max(x['n'] for x in a.values())>=10)
    def test_no_post_start_prediction(self):
        self.seed()
        self.con.execute('DELETE FROM forecasts WHERE race_id=?',('DEMO_20261010_08',))
        with self.assertRaisesRegex(ValueError,'発走後'):
            snapshot(self.con,'DEMO_20261010_08','2026-10-10T17:16:00+09:00')
    def test_consensus_only_earlier_picks(self):
        self.seed()
        initial=analyze_race(self.con,'DEMO_20261027_08')
        x=initial['ranked'][0]['combo']
        count=sum(row['support_n'] for row in initial['ranked'])
        self.con.execute('INSERT INTO picks VALUES (?,?,?,?,?,?,?,?)',
                         ('late','sample_a','DEMO_20261027_08','2車単',x,100,'2026-10-27T17:00:00+09:00',''))
        updated=analyze_race(self.con,'DEMO_20261027_08')
        self.assertEqual(sum(row['support_n'] for row in updated['ranked']),count)
    def test_late_results_not_in_tipster_weight(self):
        self.seed()
        early=settled_tipster_stats(self.con,'2026-10-10T17:00:00+09:00')
        self.assertEqual(early,{})
        later=settled_tipster_stats(self.con,'2026-10-12T15:00:00+09:00')
        self.assertTrue(later)
    def test_demo_web_renders_and_escapes(self):
        self.seed()
        page=render(self.db,{'view':'race','id':'DEMO_20261010_08'})
        self.assertIn('統合スコア',page)
        self.assertIn('架空データ',page)
        page2=render(self.db,{'view':'tipsters'})
        self.assertIn('調整係数',page2)
    def test_sample_backtest(self):
        self.seed()
        data=backtest(self.con)
        self.assertGreaterEqual(data['races'],1)
        self.assertEqual(data['spent'],100*data['races'])
        self.assertGreaterEqual(data['returned'],0)
    def test_import_rejects_invalid_combos(self):
        self.seed()
        csvfile=Path(self.folder.name)/'invalid.csv'
        csvfile.write_text('race_id,bet_type,combo,decimal_odds,captured_at\nDEMO_20261010_08,2車単,11,3,2026-10-10T16:00:00+09:00\n')
        with self.assertRaisesRegex(ValueError,'combo'):
            import_csv(self.con,'odds',csvfile)
    def test_odds_after_snapshot_not_used(self):
        self.seed()
        rid='DEMO_20261027_08'
        info=analyze_race(self.con,rid)
        combo=info['ranked'][0]['combo']
        original=next(x for x in info['ranked'] if x['combo']==combo)['odds']
        self.con.execute('INSERT INTO odds VALUES (?,?,?,?,?)',
             (rid,'2車単',combo,5000.0,'2026-10-27T17:00:00+09:00'))
        updated=analyze_race(self.con,rid)
        self.assertEqual(original,next(x for x in updated['ranked'] if x['combo']==combo)['odds'])
    def test_bad_timezones(self):
        with self.assertRaises(ValueError):
            parse_time('2026-10-10T17:00:00')
    def test_readonly_cannot_insert(self):
        self.seed()
        with connect(self.db,readonly=True) as ro:
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("INSERT INTO tipsters VALUES ('bad','name','manual','')")

if __name__=='__main__': unittest.main()
