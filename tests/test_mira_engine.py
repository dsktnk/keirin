"""Regression checks for the experimental MIRA challenger (synthetic inputs only)."""
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect,init_db
from keirinlab.realrace import register_race,baseline,settle_race
from keirinlab.mira_engine import compute,prediction,preview,freeze,paired_scorecard,panel

CARD={
    'race_id':'MIRA_UNIT_TEST_R1','venue':'架空競輪場','race_no':1,
    'start_at':'2025-09-01T18:00:00+09:00',
    'captured_at':'2025-09-01T10:00:00+09:00',
    'source_url':'https://example.invalid/synthetic-card',
    'entrants':[
      {'car_no':1,'rider_name':'架空A','rating':92.0,'win_rate':.4,'place_rate':.6,'line_id':'A','style':'逃'},
      {'car_no':2,'rider_name':'架空B','rating':88.0,'win_rate':.2,'place_rate':.5,'line_id':'A','style':'追'},
      {'car_no':3,'rider_name':'架空C','rating':85.0,'win_rate':.1,'place_rate':.2,'line_id':'B','style':'両'}
    ]
}
AT='2025-09-01T12:00:00+09:00'

class MiraEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'research.sqlite3'
        self.con=connect(self.db)
        init_db(self.con,ROOT/'schema.sql')
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def register(self):
        register_race(self.con,CARD,at=AT)
    def ready(self):
        self.register()
        baseline(self.con,CARD['race_id'],at=AT)

    def test_distribution_is_normalized_and_ordered(self):
        prob=compute(CARD['entrants'])
        self.assertEqual(set(prob),{'12','13','21','23','31','32'})
        self.assertAlmostEqual(sum(prob.values()),1.0)
        self.assertTrue(all(0<v<1 for v in prob.values()))
        self.assertNotEqual(prob['12'],prob['21'])
        d=prediction(CARD['entrants'])
        self.assertEqual(len(d['picks']),3)
        self.assertEqual(len(set(d['picks'])),3)
        self.assertIn(d['confidence'],('low','medium'))
        self.assertNotIn('高精度',d['rationale'])

    def test_cannot_preview_after_start_or_with_future_data(self):
        self.register()
        with self.assertRaisesRegex(ValueError,'発走後'):
            preview(self.con,CARD['race_id'],at='2025-09-01T18:01:00+09:00')
        with self.assertRaisesRegex(ValueError,'確認済み'):
            preview(self.con,CARD['race_id'],at='2025-09-01T09:00:00+09:00')

    def test_baseline_required_and_immutability(self):
        self.register()
        with self.assertRaisesRegex(ValueError,'比較モデル'):
            freeze(self.con,CARD['race_id'],at=AT)
        baseline(self.con,CARD['race_id'],at=AT)
        snap=freeze(self.con,CARD['race_id'],at=AT)
        self.assertEqual(snap['model_version'],'mira-rule-v1.0')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM mira_rule_forecasts').fetchone()[0],6)
        with self.assertRaisesRegex(ValueError,'上書き禁止'):
            freeze(self.con,CARD['race_id'],at=AT)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM mira_rule_forecasts').fetchone()[0],6)

    def test_paired_scoring_requires_real_result(self):
        self.ready()
        freeze(self.con,CARD['race_id'],at=AT)
        self.assertEqual(paired_scorecard(self.con,now='2025-09-01T19:30:00+09:00')['n'],0)
        settle_race(self.con,{'race_id':CARD['race_id'],
                   'first_no':1,'second_no':2,'third_no':3,
                   'payout_yen_per_100':800,
                   'source_url':'https://example.invalid/final'},at='2025-09-01T19:00:00+09:00')
        early=paired_scorecard(self.con,now='2025-09-01T18:30:00+09:00')
        self.assertEqual(early['n'],0)
        later=paired_scorecard(self.con,now='2025-09-01T20:00:00+09:00')
        self.assertEqual(later['n'],1)
        for key in ('baseline','mira'):
            self.assertEqual(later[key]['n'],1)
            self.assertTrue(math.isfinite(later[key]['logloss']))
            self.assertGreaterEqual(later[key]['brier'],0)
            self.assertLessEqual(later[key]['hit_rate'],1)
        self.assertIn('MIRAルール',panel(self.con))

    def test_future_feature_excluded_in_paired_comparison(self):
        self.ready()
        freeze(self.con,CARD['race_id'],at=AT)
        settle_race(self.con,{'race_id':CARD['race_id'],
            'first_no':1,'second_no':2,'third_no':3,
            'payout_yen_per_100':800,
            'source_url':'https://example.invalid/final'},at='2025-09-01T19:00:00+09:00')
        self.con.execute('UPDATE entrants SET captured_at=? WHERE car_no=2',
                         ('2025-09-01T13:00:00+09:00',))
        self.assertEqual(paired_scorecard(self.con,now='2025-09-01T20:00:00+09:00')['n'],0)

    def test_detects_decision_probability_mismatch(self):
        self.ready()
        freeze(self.con,CARD['race_id'],at=AT)
        settle_race(self.con,{'race_id':CARD['race_id'],
            'first_no':1,'second_no':2,'third_no':3,
            'payout_yen_per_100':800,
            'source_url':'https://example.invalid/final'},at='2025-09-01T19:00:00+09:00')
        self.con.execute('UPDATE mira_rule_decisions SET best_combo=? WHERE race_id=?',
                         ('31',CARD['race_id']))
        report=paired_scorecard(self.con,now='2025-09-01T20:00:00+09:00')
        self.assertEqual(report['n'],0)
        self.assertEqual(report['excluded']['decision_mismatch'],1)

    def test_no_fabricated_line(self):
        a=[dict(e,line_id='') for e in CARD['entrants']]
        p1=compute(a)
        a[1]['line_id']='B'
        p2=compute(a)
        self.assertEqual(p1,p2)
        a[0]['line_id']='B'
        p3=compute(a)
        self.assertNotAlmostEqual(p1['12'],p3['12'],places=5)

    def test_demo_not_used(self):
        self.ready()
        freeze(self.con,CARD['race_id'],at=AT)
        self.con.execute('UPDATE races SET is_demo=1')
        self.assertEqual(paired_scorecard(self.con)['n'],0)

if __name__=='__main__':
    unittest.main()
