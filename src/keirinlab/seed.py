"""Deterministic synthetic fixtures. No real riders, odds or TIPSTAR accounts."""
import random
from datetime import datetime, timedelta
from .core import JST, compute_probabilities, snapshot, now_jst


def seed_demo(con):
    if con.execute('SELECT 1 FROM races LIMIT 1').fetchone():
        raise ValueError('DBにデータがあります。デモ投入は空のDBだけで実行してください')
    rng = random.Random(20261020)
    names = ['架空選手Ａ','架空選手Ｂ','架空選手Ｃ','架空選手Ｄ','架空選手Ｅ','架空選手Ｆ','架空選手Ｇ']
    tipsters = [('sample_a','デモ予想師・堅実派'),('sample_b','デモ予想師・穴狙い'),('sample_c','デモ予想師・展開派'),('sample_d','デモ予想師・直感派')]
    with con:
        con.executemany('INSERT INTO tipsters VALUES (?,?,?,?)',[(tid,name,'demo','') for tid,name in tipsters])
    # 18 races spanning the display date, including upcoming races.
    base = datetime(2026,10,10,17,15,tzinfo=JST)
    today = datetime.now(JST)
    for idx in range(18):
        start = base + timedelta(days=idx)
        race_id = 'DEMO_202610{:02d}_08'.format(10+idx)
        stamp = lambda delta: (start+timedelta(minutes=delta)).isoformat(timespec='seconds')
        with con:
            con.execute('INSERT INTO races VALUES (?,?,?,?,?,?,?)',
                        (race_id,start.date().isoformat(),['松阪','防府','小倉'][idx%3],8,'A級予選・架空',stamp(0),1))
            for car in range(1,8):
                rating = round(78 + rng.random()*20,1)
                wr = round(0.07 + rng.random()*0.28,3)
                pr = round(wr + rng.random()*(0.69-wr),3)
                con.execute('INSERT INTO entrants VALUES (?,?,?,?,?,?,?,?,?)',
                            (race_id,car,names[car-1],rating,wr,pr,str((car-1)//2+1),['逃','追','両'][car%3],stamp(-100)))
        es = con.execute('SELECT * FROM entrants WHERE race_id=? ORDER BY car_no',(race_id,)).fetchall()
        true_probs = compute_probabilities(es)
        # Invented market odds, never from official sources.
        with con:
            for combo,p in true_probs.items():
                od = max(1.3,round((1/p)*rng.uniform(0.54,1.08),1))
                con.execute('INSERT INTO odds VALUES (?,?,?,?,?)',(race_id,'2車単',combo,od,stamp(-50)))
        sorted_combos = sorted(true_probs,key=true_probs.get,reverse=True)
        with con:
            for j,(tid,_) in enumerate(tipsters):
                if j==0:
                    cs = sorted_combos[:2]
                elif j==1:
                    cs = rng.sample(sorted_combos[8:],2)
                elif j==2:
                    cs = sorted_combos[1:4:2]
                else:
                    cs = rng.sample(sorted_combos,2)
                for pos, combo in enumerate(cs):
                    con.execute('INSERT INTO picks VALUES (?,?,?,?,?,?,?,?)',
                                ('{}_{}_{}'.format(race_id,tid,pos),tid,race_id,'2車単',combo,100,stamp(-40),''))
        snapshot(con,race_id,stamp(-30))
        # Realistic temporal completeness: settle only before actual now.
        if start+timedelta(minutes=30) >= today:
            continue
        roll = rng.random()
        cum = 0
        winner = list(true_probs)[-1]
        for combo,p in true_probs.items():
            cum += p
            if roll <= cum:
                winner=combo
                break
        third = rng.choice([str(v) for v in range(1,8) if str(v) not in winner])
        od = con.execute('SELECT decimal_odds FROM odds WHERE race_id=? AND combo=?',(race_id,winner)).fetchone()['decimal_odds']
        pay = round(100*od/10)*10
        with con:
            con.execute('INSERT INTO results VALUES (?,?,?,?,?)',
                        (race_id,int(winner[0]),int(winner[1]),int(third),stamp(30)))
            con.execute('INSERT INTO payouts VALUES (?,?,?,?)',(race_id,'2車単',winner,pay))
    return con.execute('SELECT COUNT(*) FROM races').fetchone()[0]
