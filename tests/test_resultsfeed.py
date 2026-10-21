import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from keirinlab.core import connect,init_db
from keirinlab.realrace import register_race,baseline,predict_mira,mira_summary
from keirinlab.resultsfeed import parse_result_feed,reconcile

DAY='2026-10-21'
AT='2026-10-21T15:00:00+09:00'
LATER='2026-10-21T22:00:00+09:00'
URL='https://example.invalid/actual-results.json'
CARD={
 'race_id':'LIVE_202610211201','venue':'架空場','race_no':1,
 'class_name':'','start_at':'2026-10-21T17:00:00+09:00',
 'captured_at':'2026-10-21T14:00:00+09:00',
 'source_url':'https://example.invalid/card',
 'entrants':[{'car_no':i,'rider_name':'架空選手'+str(i),
              'rating':90+i,'win_rate':.2,'place_rate':.4,'line_id':'','style':'追'} for i in (1,2,3)]
}
RECORD={'race_id':'202610211201','venue':'架空場','race_number':1,
        'n_cars':3,'result_top3':[1,2,3],
        'result_places':[[1],[2],[3]],
        'payouts':{'exacta':[{'combo':[1,2],'payout':750}]}}

def result_bytes(row=None):
    return json.dumps({'date':DAY,'races':[row or RECORD]},ensure_ascii=False).encode()

class SettlementTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.con=connect(Path(self.tmp.name)/'test.sqlite3')
        init_db(self.con,ROOT/'schema.sql')
        register_race(self.con,CARD,at=AT)
        baseline(self.con,CARD['race_id'],at=AT)
        predict_mira(self.con,{
            'race_id':CARD['race_id'],'picks':['12','13','21'],
            'confidence':'medium','rationale':'テスト用の架空出走表から検証する理由を残す。'
        },at=AT)
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def check(self,raw=None,when=LATER,save=False):
        return reconcile(self.con,raw or result_bytes(),DAY,source_url=URL,at=when,dry_run=not save)
    def test_parse_and_dry_run(self):
        self.assertEqual(len(parse_result_feed(result_bytes(),DAY)),1)
        r=self.check()
        self.assertEqual(r['eligible'],1)
        self.assertEqual(r['settled'],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM results').fetchone()[0],0)
    def test_save_and_idempotent(self):
        s=self.check(save=True)
        self.assertEqual(s['settled'],1)
        self.assertEqual(self.check(save=True)['already'],1)
        m=mira_summary(self.con)
        self.assertEqual(m['hits'],1)
        self.assertAlmostEqual(m['roi'],7.5)
    def test_not_final_yet(self):
        r=self.check(when=AT,save=True)
        self.assertEqual(r['settled'],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM results').fetchone()[0],0)
    def test_wrong_venue(self):
        v=dict(RECORD,venue='別の場')
        r=self.check(result_bytes(v),save=True)
        self.assertEqual(r['settled'],0)
    def test_wrong_payout(self):
        v=dict(RECORD,payouts={'exacta':[{'combo':[2,1],'payout':750}]})
        self.assertEqual(self.check(result_bytes(v),save=True)['settled'],0)
    def test_missing_and_ambiguous_results(self):
        for changed in [
            dict(RECORD,result_top3=None),
            dict(RECORD,result_top3=[1,1,3]),
            dict(RECORD,result_places=[[1,2],[3]]),
            dict(RECORD,payouts={'exacta':[]}),
            dict(RECORD,n_cars=7),
        ]:
            with self.subTest(changed=changed):
                self.assertEqual(self.check(result_bytes(changed),save=True)['settled'],0)
    def test_date_mismatch(self):
        payload=json.dumps({'date':'2026-10-20','races':[RECORD]}).encode()
        with self.assertRaisesRegex(ValueError,'対象日'):
            self.check(payload)
    def test_duplicate_race_id(self):
        data=json.dumps({'date':DAY,'races':[RECORD,RECORD]}).encode()
        with self.assertRaisesRegex(ValueError,'重複'):
            self.check(data)

if __name__=='__main__':
    unittest.main()
