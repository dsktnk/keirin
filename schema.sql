PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS races (
  id TEXT PRIMARY KEY, race_date TEXT NOT NULL, venue TEXT NOT NULL,
  race_no INTEGER NOT NULL CHECK(race_no BETWEEN 1 AND 12),
  class_name TEXT NOT NULL DEFAULT '', start_at TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0 CHECK(is_demo IN (0,1))
);
CREATE TABLE IF NOT EXISTS entrants (
  race_id TEXT NOT NULL REFERENCES races(id), car_no INTEGER NOT NULL CHECK(car_no BETWEEN 1 AND 9),
  rider_name TEXT NOT NULL, rating REAL NOT NULL, win_rate REAL NOT NULL CHECK(win_rate BETWEEN 0 AND 1),
  place_rate REAL NOT NULL CHECK(place_rate BETWEEN 0 AND 1),
  line_id TEXT NOT NULL DEFAULT '', style TEXT NOT NULL DEFAULT '', captured_at TEXT NOT NULL,
  PRIMARY KEY(race_id,car_no)
);
CREATE TABLE IF NOT EXISTS odds (
  race_id TEXT NOT NULL REFERENCES races(id), bet_type TEXT NOT NULL CHECK(bet_type='2車単'),
  combo TEXT NOT NULL, decimal_odds REAL NOT NULL CHECK(decimal_odds > 1), captured_at TEXT NOT NULL,
  PRIMARY KEY(race_id,bet_type,combo,captured_at)
);
CREATE TABLE IF NOT EXISTS tipsters (
  id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual', profile_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS picks (
  id TEXT PRIMARY KEY, tipster_id TEXT NOT NULL REFERENCES tipsters(id),
  race_id TEXT NOT NULL REFERENCES races(id), bet_type TEXT NOT NULL CHECK(bet_type='2車単'),
  combo TEXT NOT NULL, stake_yen INTEGER NOT NULL CHECK(stake_yen >= 100 AND stake_yen % 100 = 0),
  published_at TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS results (
  race_id TEXT PRIMARY KEY REFERENCES races(id), first_no INTEGER NOT NULL,
  second_no INTEGER NOT NULL, third_no INTEGER NOT NULL, finalized_at TEXT NOT NULL,
  CHECK(first_no!=second_no AND second_no!=third_no AND first_no!=third_no)
);
CREATE TABLE IF NOT EXISTS payouts (
  race_id TEXT NOT NULL REFERENCES races(id), bet_type TEXT NOT NULL CHECK(bet_type='2車単'),
  combo TEXT NOT NULL, payout_yen_per_100 INTEGER NOT NULL CHECK(payout_yen_per_100 >= 0),
  PRIMARY KEY(race_id,bet_type,combo)
);
CREATE TABLE IF NOT EXISTS forecasts (
  race_id TEXT NOT NULL REFERENCES races(id), bet_type TEXT NOT NULL CHECK(bet_type='2車単'),
  combo TEXT NOT NULL, probability REAL NOT NULL CHECK(probability BETWEEN 0 AND 1),
  model_version TEXT NOT NULL, snapshot_at TEXT NOT NULL,
  PRIMARY KEY(race_id,bet_type,combo)
);
CREATE INDEX IF NOT EXISTS idx_picks_tipster ON picks(tipster_id,race_id);
CREATE INDEX IF NOT EXISTS idx_races_date ON races(start_at);
CREATE INDEX IF NOT EXISTS idx_results_final ON results(finalized_at);
