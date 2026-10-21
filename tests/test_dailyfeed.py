"""Offline tests for v0.8 daily pre-race import; no source network calls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tools'))
from keirinlab.core import connect,init_db
from keirinlab.dailyfeed import candidates,ingest,data_status
from ingest_daily import daily_url,retrieve

OBS='2026-10-21T09:00:00+09:00'
DAY='2026-10-21'
URL='https://raw.githubusercontent.com/snarfnet/keirin-data/main/entries_20261021.json'


def runner(no,clock,rate=40.0):
    return {'race_id':'20261021'+str(1200+no),
            'venue':'架空競輪場','race_no':no,'start_time':clock,
            'entries':[{
                'umaban':car,'name':'架空選手'+str(car),'score':85.0+car,
                'style':'追','win_rate':rate/4,'top2_rate':rate
            } for car in (1,2,3)]}


def payload(*races):
    return json.dumps({'date':'20261021','races':list(races)},ensure_ascii=False).encode('utf-8')


class DummyResponse:
    headers={'Content-Type':'application/json'}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return payload(runner(1,'11:00'))[:limit]


class DummyOpener:
    def __init__(self):self.calls=0
    def open(self,request,timeout=0):
        self.calls+=1
        return DummyResponse()


class DailyFeedTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'keirin.sqlite3'
        self.con=connect(self.db)
        init_db(self.con,ROOT/'schema.sql')
    def tearDown(self):
        self.con.close()
        self.temp.cleanup()
    def test_parse_rates_and_no_invented_lines(self):
        cards,meta=candidates(payload(runner(1,'11:00')),DAY,OBS,url=URL)
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]['race_id'],'LIVE_202610211201')
        self.assertAlmostEqual(cards[0]['entrants'][0]['win_rate'],.1)
        self.assertAlmostEqual(cards[0]['entrants'][0]['place_rate'],.4)
        self.assertEqual(cards[0]['entrants'][0]['line_id'],'')
        self.assertEqual(cards[0]['captured_at'],OBS)
    def test_skip_started_and_too_close(self):
        cards,meta=candidates(payload(runner(1,'08:50'),runner(2,'09:20'),
                                      runner(3,'11:00')),DAY,OBS,url=URL)
        self.assertEqual(len(cards),1)
        self.assertEqual(meta['dropped']['already_started_or_soon'],2)
    def test_max_races_selects_earliest(self):
        cards,meta=candidates(payload(runner(1,'14:00'),runner(2,'11:00'),runner(3,'10:00')),
                              DAY,OBS,max_races=2,url=URL)
        self.assertEqual([c['race_no'] for c in cards],[3,2])
    def test_does_not_use_missing_values(self):
        broken=runner(1,'12:00')
        del broken['entries'][0]['win_rate']
        cards,meta=candidates(payload(broken),DAY,OBS,url=URL)
        self.assertEqual(cards,[])
        self.assertEqual(meta['dropped']['invalid'],1)
    def test_reject_mismatched_day(self):
        with self.assertRaisesRegex(ValueError,'日付'):
            candidates(payload(runner(1,'11:00')),'2026-10-22',OBS,url=URL)
    def test_import_and_idempotence(self):
        cards,_=candidates(payload(runner(1,'12:00')),DAY,OBS,url=URL)
        first=ingest(self.con,cards,OBS)
        self.assertEqual(first['created'],1)
        self.assertEqual(first['baseline_created'],1)
        self.assertEqual(first['mira_rule_created'],1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM mira_rule_forecasts WHERE race_id='LIVE_202610211201'").fetchone()[0],6)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM forecasts WHERE race_id='LIVE_202610211201'").fetchone()[0],6)
        again=ingest(self.con,cards,OBS)
        self.assertEqual(again['unchanged'],1)
        self.assertEqual(again['mira_rule_created'],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM races WHERE id LIKE ?',('LIVE_%',)).fetchone()[0],1)
    def test_status_read_only(self):
        self.assertIn('登録 <b>0</b>',data_status(self.con))
        cards,_=candidates(payload(runner(1,'12:00')),DAY,OBS,url=URL)
        ingest(self.con,cards,OBS)
        with connect(self.db,readonly=True) as ro:
            self.assertIn('登録 <b>1</b>',data_status(ro))
    def test_recovers_missing_baseline_without_modifying_race(self):
        cards,_=candidates(payload(runner(1,'12:00')),DAY,OBS,url=URL)
        ingest(self.con,cards,OBS)
        self.con.execute("DELETE FROM forecasts WHERE race_id='LIVE_202610211201'")
        self.con.commit()
        report=ingest(self.con,cards,OBS)
        self.assertEqual(report['unchanged'],1)
        self.assertEqual(report['baseline_created'],1)
        self.assertEqual(report['mira_rule_created'],0)  # challenger snapshot was already frozen
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM forecasts WHERE race_id='LIVE_202610211201'").fetchone()[0],6)
    def test_source_protection_url(self):
        self.assertEqual(daily_url(DAY),URL)
        with self.assertRaises(ValueError):
            daily_url('2026-02-31')
    def test_throttle(self):
        dummy=DummyOpener()
        marker=Path(self.temp.name)/'last'
        retrieve(URL,marker,opener=dummy,clock=lambda:10000)
        with self.assertRaisesRegex(ValueError,'取得間隔'):
            retrieve(URL,marker,opener=dummy,clock=lambda:10020)
        self.assertEqual(dummy.calls,1)


if __name__=='__main__':
    unittest.main()
