import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect, init_db
from keirinlab.realrace import (register_race,baseline,predict_mira,settle_race,
                                mira_summary,mira_panel)
from keirinlab.webapp import render

# Synthetic fixtures with past timestamps only, NEVER actual race results.
CARD = {
  'race_id':'UNIT_TEST_20250901_R1','venue':'架空バンク','race_no':1,
  'class_name':'A級（架空）','start_at':'2025-09-01T18:00:00+09:00',
  'captured_at':'2025-09-01T12:00:00+09:00',
  'source_url':'https://example.invalid/synthetic',
  'entrants': [
    {'car_no':1,'rider_name':'架空A','rating':91.0,'win_rate':0.3,'place_rate':0.5,'line_id':'A','style':'逃'},
    {'car_no':2,'rider_name':'架空B','rating':89.0,'win_rate':0.2,'place_rate':0.4,'line_id':'A','style':'追'},
    {'car_no':3,'rider_name':'架空C','rating':87.0,'win_rate':0.1,'place_rate':0.3,'line_id':'B','style':'両'}
  ]
}
PRED = {'race_id':'UNIT_TEST_20250901_R1','picks':['12','13','21'],
        'confidence':'medium',
        'rationale':'架空の能力差とラインの並びを比較して、本命から順に選定。'}
RESULT = {'race_id':'UNIT_TEST_20250901_R1',
          'first_no':1,'second_no':2,'third_no':3,
          'payout_yen_per_100':680,
          'source_url':'https://example.invalid/synthetic-results'}


class RealRaceTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'sqlite3.db'
        self.con=connect(self.path)
        init_db(self.con,ROOT/'schema.sql')
    def tearDown(self):
        self.con.close()
        self.folder.cleanup()
    def add(self):
        return register_race(self.con,CARD,at='2025-09-01T12:30:00+09:00')
    def freeze(self):
        return baseline(self.con,CARD['race_id'],at='2025-09-01T13:00:00+09:00')
    def predict(self):
        return predict_mira(self.con,PRED,at='2025-09-01T14:00:00+09:00')
    def settle(self):
        return settle_race(self.con,RESULT,at='2025-09-01T19:00:00+09:00')
    def test_full_workflow(self):
        self.assertEqual(self.add(),'created')
        self.assertEqual(self.add(),'unchanged')
        self.assertEqual(self.freeze(),6)
        self.predict()
        self.settle()
        stats=mira_summary(self.con)
        self.assertEqual((stats['total'],stats['settled'],stats['hits']),(1,1,1))
        self.assertAlmostEqual(stats['roi'],6.8)
        self.assertIn('架空バンク',mira_panel(self.con))
        with connect(self.path,readonly=True) as ro:
            html=render(self.path,{'view':'research'})
            self.assertIn('MIRAの発走前予想',html)
    def test_cannot_register_after_start(self):
        with self.assertRaisesRegex(ValueError,'発走前'):
            register_race(self.con,CARD,at='2025-09-01T18:30:00+09:00')
    def test_registration_rollback(self):
        card=dict(CARD)
        card['entrants']=[dict(x) for x in CARD['entrants']]
        card['entrants'][1]['car_no']=1
        with self.assertRaisesRegex(ValueError,'重複'):
            register_race(self.con,card,at='2025-09-01T12:30:00+09:00')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM races').fetchone()[0],0)
    def test_no_silent_updates(self):
        self.add()
        card=dict(CARD)
        card['venue']='別の競輪場'
        with self.assertRaisesRegex(ValueError,'上書き'):
            register_race(self.con,card,at='2025-09-01T12:30:00+09:00')
    def test_predict_requires_baseline(self):
        self.add()
        with self.assertRaisesRegex(ValueError,'baseline'):
            self.predict()
    def test_prediction_cannot_be_revised_or_post_start(self):
        self.add()
        self.freeze()
        self.predict()
        with self.assertRaisesRegex(ValueError,'上書き'):
            self.predict()
        with self.assertRaisesRegex(ValueError,'発走後'):
            predict_mira(self.con,PRED,at='2025-09-01T18:10:00+09:00')
    def test_result_immutable(self):
        self.add()
        self.settle()
        with self.assertRaisesRegex(ValueError,'上書き'):
            self.settle()
    def test_result_before_start_rejected(self):
        self.add()
        with self.assertRaisesRegex(ValueError,'発走前'):
            settle_race(self.con,RESULT,at='2025-09-01T17:00:00+09:00')
    def test_readonly_empty_dashboard(self):
        self.add()
        with connect(self.path,readonly=True) as ro:
            self.assertEqual(mira_summary(ro)['total'],0)
            self.assertIn('0</b>件',mira_panel(ro))
    def test_forecasts_normalized(self):
        self.add()
        self.freeze()
        rows=self.con.execute('SELECT probability FROM forecasts WHERE race_id=?',(CARD['race_id'],)).fetchall()
        self.assertEqual(len(rows),6)
        self.assertAlmostEqual(sum(r[0] for r in rows),1)


if __name__=='__main__':
    unittest.main()
