"""Deterministic tests for the outcome-blind research scorecard."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from keirinlab.core import connect, init_db
from keirinlab.research import scorecard, research_view


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.con = connect(Path(self.temp.name)/'eval.sqlite3')
        init_db(self.con, ROOT/'schema.sql')
        self.con.execute('INSERT INTO races VALUES (?,?,?,?,?,?,?)',
                         ('R1','2026-10-10','松江',1,'A級','2026-10-10T12:00:00+09:00',0))
        for car in (1,2,3):
            self.con.execute('INSERT INTO entrants VALUES (?,?,?,?,?,?,?,?,?)',
                             ('R1',car,'選手'+str(car),85,0.2,0.4,'','追','2026-10-10T10:00:00+09:00'))
        combos = ['12','13','21','23','31','32']
        for c in combos:
            self.con.execute('INSERT INTO forecasts VALUES (?,?,?,?,?,?)',
                             ('R1','2車単',c,0.5 if c == '12' else 0.1,
                              'baseline','2026-10-10T11:00:00+09:00'))
        self.con.execute('INSERT INTO results VALUES (?,?,?,?,?)',
                         ('R1',1,2,3,'2026-10-10T12:30:00+09:00'))
        self.con.execute('INSERT INTO payouts VALUES (?,?,?,?)',
                         ('R1','2車単','12',600))
        self.con.commit()
    def tearDown(self):
        self.con.close()
        self.temp.cleanup()
    def evaluate(self):
        return scorecard(self.con, 'real', now='2026-10-11T00:00:00+09:00')
    def test_complete_distribution(self):
        s=self.evaluate()
        self.assertEqual(s['evaluated'],1)
        self.assertEqual(s['top1_hits'],1)
        self.assertAlmostEqual(s['top1_rate'],1)
        self.assertAlmostEqual(s['top3_rate'],1)
        self.assertAlmostEqual(s['mean_logloss'],0.6931471805599453)
        self.assertAlmostEqual(s['mean_brier'],0.3)
        self.assertEqual(s['roi'],6)
    def test_missing_payout_not_zero_return(self):
        self.con.execute('DELETE FROM payouts')
        s=self.evaluate()
        self.assertEqual(s['evaluated'],1)
        self.assertIsNone(s['roi'])
        self.assertEqual(s['paid_races'],0)
    def test_future_result_not_counted(self):
        s=scorecard(self.con,'real',now='2026-10-10T12:20:00+09:00')
        self.assertEqual(s['evaluated'],0)
        self.assertEqual(s['counts']['not_finalized'],1)
    def test_prediction_after_start_excluded(self):
        self.con.execute('UPDATE forecasts SET snapshot_at=?',
                         ('2026-10-10T12:01:00+09:00',))
        s=self.evaluate()
        self.assertEqual(s['evaluated'],0)
        self.assertEqual(s['counts']['invalid_snapshot'],1)
    def test_late_entrant_excluded(self):
        self.con.execute('UPDATE entrants SET captured_at=? WHERE car_no=2',
                         ('2026-10-10T11:30:00+09:00',))
        s=self.evaluate()
        self.assertEqual(s['evaluated'],0)
        self.assertEqual(s['counts']['late_entries'],1)
    def test_incomplete_distribution_excluded(self):
        self.con.execute("DELETE FROM forecasts WHERE combo='32'")
        s=self.evaluate()
        self.assertEqual(s['evaluated'],0)
        self.assertEqual(s['counts']['invalid_distribution'],1)
    def test_demo_is_separate(self):
        self.con.execute("UPDATE races SET is_demo=1")
        self.assertEqual(self.evaluate()['evaluated'],0)
        self.assertEqual(scorecard(self.con,'demo',now='2026-10-11T00:00:00+09:00')['evaluated'],1)
    def test_real_page(self):
        self.assertIn('MIRA予測',research_view(self.con))
    def test_no_forecast(self):
        self.con.execute('DELETE FROM forecasts')
        self.assertEqual(self.evaluate()['counts']['missing_forecast'],1)


if __name__ == '__main__':
    unittest.main()
