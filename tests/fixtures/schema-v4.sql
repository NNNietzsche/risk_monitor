PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('vessel','aircraft')),
 name TEXT NOT NULL, imo TEXT UNIQUE, mmsi TEXT UNIQUE, registration TEXT UNIQUE,
 CHECK((kind='vessel' AND (imo IS NOT NULL OR mmsi IS NOT NULL)) OR (kind='aircraft' AND registration IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS flight_instances(
 id TEXT PRIMARY KEY, aircraft_id TEXT REFERENCES assets(id), carrier TEXT NOT NULL,
 flight_number TEXT NOT NULL, service_date TEXT NOT NULL, departure TEXT NOT NULL, arrival TEXT NOT NULL,
 scheduled_departure TEXT NOT NULL, scheduled_arrival TEXT NOT NULL,
 UNIQUE(carrier,flight_number,service_date,departure,arrival)
);
CREATE TABLE IF NOT EXISTS regions(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL, geometry TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_versions(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, version INTEGER NOT NULL, engine_version TEXT NOT NULL,
 config TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitors(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
 asset_id TEXT UNIQUE REFERENCES assets(id), flight_id TEXT UNIQUE REFERENCES flight_instances(id),
 rule_id TEXT NOT NULL REFERENCES rule_versions(id), provider TEXT NOT NULL DEFAULT 'mock-v1',
 enabled INTEGER NOT NULL DEFAULT 1, cursor INTEGER NOT NULL DEFAULT 0,
 health TEXT NOT NULL DEFAULT 'unknown', last_poll_at TEXT, last_error TEXT,
 state TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
 CHECK((kind IN ('vessel','aircraft') AND asset_id IS NOT NULL AND flight_id IS NULL)
    OR (kind='flight' AND asset_id IS NULL AND flight_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS raw_records(
 id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
 provider TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
 sha256 TEXT NOT NULL, outcome TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS observations(
 id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
 raw_id TEXT UNIQUE NOT NULL REFERENCES raw_records(id),
 observed_at TEXT NOT NULL, data TEXT NOT NULL, quality TEXT NOT NULL, UNIQUE(monitor_id,observed_at)
);
CREATE TABLE IF NOT EXISTS evaluations(
 id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
 observation_id TEXT NOT NULL REFERENCES observations(id), rule_id TEXT NOT NULL REFERENCES rule_versions(id),
 evaluated_at TEXT NOT NULL, result TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_events(
 id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
 evaluation_id TEXT NOT NULL REFERENCES evaluations(id), rule_id TEXT NOT NULL REFERENCES rule_versions(id),
 type TEXT NOT NULL, severity TEXT NOT NULL, occurred_at TEXT NOT NULL, created_at TEXT NOT NULL,
 summary TEXT NOT NULL, evidence TEXT NOT NULL, UNIQUE(evaluation_id,type)
);
CREATE TABLE IF NOT EXISTS configuration_audit(
 id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
 action TEXT NOT NULL, before_value TEXT NOT NULL, after_value TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_monitor_time ON observations(monitor_id,observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_monitor_time ON raw_records(monitor_id,received_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_created ON risk_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_monitor_created ON risk_events(monitor_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evaluations_monitor_time ON evaluations(monitor_id,evaluated_at DESC);
-- Source context is independent of the last risk-valid position; raw evidence is immutable.
CREATE TABLE IF NOT EXISTS monitor_context(
 monitor_id TEXT PRIMARY KEY REFERENCES monitors(id),
 raw_id TEXT NOT NULL REFERENCES raw_records(id), checked_at TEXT NOT NULL, data TEXT NOT NULL
);
