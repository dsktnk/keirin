import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect,init_db
from keirinlab.feed import ingest,parse_csv_bytes,_not_local_https
from keirinlab.webapp import render


HEAD='race_id,venue_slug,date,race_no,banum,player_name,pref,age,term,player_class,running_style,gear,race_score,rank,agari,finish_type,margin,win_lose,lineup,payout\n'
ONE='abc123,matsusaka,2026-09-20,8,3,選手A,三重,33,100,A1,逃,3.92,89.1,1,11.9,逃,,,,\n'
TWO='abc123,matsusaka,2026-09-20,8,5,選手B,大阪,29,110,A1,追,3.92,88.0,2,12.0,,,,,\n'

class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'test.db'
        self.con=connect(self.db)
        self.addCleanup(self.con.close)
        init_db(self.con,ROOT/'schema.sql')

    def ingest(self,data=None):
        return ingest(self.con,ROOT,data if data is not None else (HEAD+ONE+TWO).encode(),source='test',source_ref='local-test.csv')

    def test_first_import_and_duplicates(self):
        r=self.ingest();self.assertEqual((r['new'],r['races']), (2,1))
        r=self.ingest();self.assertEqual(r['status'],'unchanged')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM feed_runs').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM feed_riders').fetchone()[0],2)

    def test_update_is_idempotent(self):
        self.ingest()
        changed=(HEAD+ONE.replace('89.1','90.2')+TWO).encode()
        r=self.ingest(changed)
        self.assertEqual(r['updated'],1)
        self.assertEqual(r['same'],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM feed_runs').fetchone()[0],2)
        self.assertEqual(self.con.execute('SELECT race_score FROM feed_riders WHERE car_no=3').fetchone()[0],90.2)

    def test_atomic_bad_csv(self):
        self.ingest()
        with self.assertRaises(ValueError):
            self.ingest((HEAD+ONE+TWO.replace(',5,',',3,')).encode())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM feed_runs').fetchone()[0],1)

    def test_bad_race_no_rejected(self):
        with self.assertRaises(ValueError): self.ingest((HEAD+ONE.replace(',8,',',0,')).encode())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM feed_races').fetchone()[0],0) if self._feed_exists() else None

    def _feed_exists(self):
        return bool(self.con.execute("SELECT 1 FROM sqlite_master WHERE name='feed_races'").fetchone())

    def test_does_not_create_predictions(self):
        self.ingest()
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM races').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],0)

    def test_reject_local_remote(self):
        for url in ['http://raw.githubusercontent.com/a.csv','https://localhost/a.csv','https://127.0.0.1/a.csv','https://example.com/a.csv','https://user:pass@raw.githubusercontent.com/a.csv']:
            with self.assertRaises(ValueError): _not_local_https(url)
        self.assertEqual(_not_local_https('https://raw.githubusercontent.com/a/b/main/a.csv'),'https://raw.githubusercontent.com/a/b/main/a.csv')

    def test_html_escape_and_no_public_write(self):
        self.ingest()
        h=render(self.db,{'view':'feed'})
        self.assertIn('取得レース',h)
        self.assertIn('取得選手行',h)
        self.assertNotIn('選手A',h)
        self.assertIn('予測利用',h)

if __name__=='__main__':unittest.main()
