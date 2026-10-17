-- Candidate data is separate from accepted replay and controller inputs.
CREATE TABLE IF NOT EXISTS uita_data.adsb_trace_index (
  dataset_id text NOT NULL,
  artifact_name text NOT NULL,
  icao24 text NOT NULL,
  registration text,
  trace_start timestamptz,
  trace_end timestamptz,
  observation_count integer NOT NULL CHECK (observation_count >= 0),
  sources jsonb NOT NULL,
  PRIMARY KEY (dataset_id, artifact_name),
  FOREIGN KEY (dataset_id, artifact_name) REFERENCES uita_data.artifacts(dataset_id, name)
);
CREATE INDEX IF NOT EXISTS uita_adsb_trace_identity ON uita_data.adsb_trace_index(dataset_id, registration, icao24);
CREATE TABLE IF NOT EXISTS uita_data.adsb_candidates (
  dataset_id text NOT NULL REFERENCES uita_data.datasets(id),
  release_tag text NOT NULL,
  operation_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('arr','dep')),
  icao24 text NOT NULL,
  payload jsonb NOT NULL,
  PRIMARY KEY (dataset_id, release_tag, operation_id)
);
REVOKE ALL ON uita_data.adsb_trace_index, uita_data.adsb_candidates FROM PUBLIC;
