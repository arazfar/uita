-- Dedicated schema avoids interfering with teammates' agent/run tables.
CREATE SCHEMA IF NOT EXISTS uita_data;
REVOKE ALL ON SCHEMA uita_data FROM PUBLIC;
CREATE TABLE IF NOT EXISTS uita_data.datasets (
  id text PRIMARY KEY,
  manifest jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS uita_data.artifacts (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  name text NOT NULL,
  sha256 text NOT NULL CHECK (length(sha256)=64),
  payload bytea NOT NULL,
  PRIMARY KEY(dataset_id,name)
);
CREATE TABLE IF NOT EXISTS uita_data.arrivals (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  flight_id text NOT NULL,
  operation_time timestamptz NOT NULL,
  local_date date NOT NULL,
  split text NOT NULL CHECK (split IN ('train','validation','test')),
  payload jsonb NOT NULL,
  PRIMARY KEY(dataset_id,flight_id)
);
CREATE INDEX IF NOT EXISTS uita_arrival_time ON uita_data.arrivals(dataset_id,operation_time);
CREATE TABLE IF NOT EXISTS uita_data.tracks (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  flight_id text NOT NULL,
  payload jsonb NOT NULL,
  PRIMARY KEY(dataset_id,flight_id),
  FOREIGN KEY(dataset_id,flight_id) REFERENCES uita_data.arrivals(dataset_id,flight_id)
);
CREATE TABLE IF NOT EXISTS uita_data.weather (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  weather_id text NOT NULL,
  observed_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  PRIMARY KEY(dataset_id,weather_id),
  CHECK(available_at>=observed_at)
);
CREATE INDEX IF NOT EXISTS uita_weather_time ON uita_data.weather(dataset_id,available_at);
CREATE TABLE IF NOT EXISTS uita_data.episodes (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  episode_id text NOT NULL,
  split text NOT NULL CHECK (split IN ('train','validation','test')),
  payload jsonb NOT NULL,
  PRIMARY KEY(dataset_id,episode_id)
);
-- The service connection owns these tables. PUBLIC receives no access.
-- Expose only the causal adapter to a controller, never the owner connection.
REVOKE ALL ON ALL TABLES IN SCHEMA uita_data FROM PUBLIC;
