-- Keirin data acquisition staging. Never blend unverified historic records into forecasts.
CREATE TABLE IF NOT EXISTS feed_races (
  source TEXT NOT NULL, race_id TEXT NOT NULL,
  race_date TEXT NOT NULL, venue TEXT NOT NULL, race_no INTEGER NOT NULL,
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source,race_id)
);
CREATE TABLE IF NOT EXISTS feed_riders (
  source TEXT NOT NULL, race_id TEXT NOT NULL, car_no INTEGER NOT NULL,
  player_name TEXT NOT NULL, race_score REAL, rider_class TEXT NOT NULL DEFAULT '',
  running_style TEXT NOT NULL DEFAULT '', rank INTEGER,
  lineup TEXT NOT NULL DEFAULT '', payout_raw TEXT NOT NULL DEFAULT '',
  pref TEXT NOT NULL DEFAULT '', age INTEGER, term TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(source,race_id,car_no),
  FOREIGN KEY(source,race_id) REFERENCES feed_races(source,race_id)
);
CREATE TABLE IF NOT EXISTS feed_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, source_ref TEXT NOT NULL, source_sha256 TEXT NOT NULL,
  fetched_at TEXT NOT NULL, file_rows INTEGER NOT NULL,
  race_count INTEGER NOT NULL, new_riders INTEGER NOT NULL,
  updated_riders INTEGER NOT NULL, unchanged_riders INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_feed_runs_hash
ON feed_runs(source,source_sha256);
CREATE INDEX IF NOT EXISTS ix_feed_races_date ON feed_races(race_date,venue);
