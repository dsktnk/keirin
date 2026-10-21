import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from keirinlab.core import connect, init_db
from keirinlab.watch import import_observations, watch_stats, watch_view

HEADER = 'tipster_id,display_name,observed_at,roi_10_pct,popularity,contribution_note,source_url\n'
LINE1 = 't_a,予想師A,2026-10-10T15:00:00+09:00,110,3,,https://tipstar.com/\n'
LINE2 = 't_a,予想師A,2026-10-11T15:00:00+09:00,140,4,,https://tipstar.com/\n'


class TipstarWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = connect(Path(self.tmp.name) / 'watch.sqlite3')
        init_db(self.con, ROOT / 'schema.sql')

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_empty_view(self):
        self.assertIn('まだ観測データがありません', watch_view(self.con))

    def test_append_and_trend(self):
        s = import_observations(self.con, (HEADER + LINE1 + LINE2).encode())
        self.assertEqual(s['inserted'], 2)
        r = watch_stats(self.con)[0]
        self.assertEqual(r['n'], 2)
        self.assertEqual(r['delta'], 30.0)
        self.assertIn('TIPSTAR', watch_view(self.con))
        self.assertIn('+30.0pt', watch_view(self.con))
        self.assertEqual(import_observations(self.con, (HEADER + LINE1).encode())['unchanged'], 1)

    def test_conflicting_observation_cannot_change(self):
        import_observations(self.con, (HEADER + LINE1).encode())
        changed = LINE1.replace(',110,', ',300,')
        with self.assertRaisesRegex(ValueError, '上書き'):
            import_observations(self.con, (HEADER + changed).encode())
        self.assertEqual(watch_stats(self.con)[0]['latest']['roi_10_pct'], 110)

    def test_validate_all_before_insert(self):
        bad = 't_b,予想師B,2026-10-13T15:00:00+09:00,nan,,,\n'
        with self.assertRaisesRegex(ValueError, '回収率'):
            import_observations(self.con, (HEADER + LINE1 + bad).encode())
        self.assertEqual(watch_stats(self.con), [])

    def test_xss_escaped_and_source_url_restricted(self):
        s = 't_x,<script>alert(1)</script>,2026-10-10T15:00:00+09:00,100,,,\n'
        import_observations(self.con, (HEADER + s).encode())
        page = watch_view(self.con)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        with self.assertRaisesRegex(ValueError, 'source_url'):
            import_observations(self.con, (HEADER + LINE2.replace('https://tipstar.com/', 'https://evil.example/')).encode())

    def test_future_and_repeated_key_rejected(self):
        with self.assertRaisesRegex(ValueError, '未来'):
            import_observations(self.con, (HEADER + LINE1.replace('2026-10-10', '2099-10-10')).encode())
        with self.assertRaisesRegex(ValueError, '重複'):
            import_observations(self.con, (HEADER + LINE1 + LINE1).encode())

    def test_transaction_rolls_back_on_conflicting_record(self):
        import_observations(self.con, (HEADER + LINE1).encode())
        add = 't_b,予想師B,2026-10-10T15:00:00+09:00,110,,,\n'
        with self.assertRaisesRegex(ValueError, '上書き'):
            import_observations(self.con, (HEADER + add + LINE1.replace(',110,', ',111,')).encode())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM watch_snapshots').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
