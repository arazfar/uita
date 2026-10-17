\set ON_ERROR_STOP on
\timing on
CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS features CASCADE;
CREATE TEMP TABLE files (path text);
COPY files FROM '/tmp/files.txt';

-- One row per GeoJSON file: alt is NULL for the flight itself, or swim-path / swim-approach / swim-takeoff
CREATE TABLE features AS
SELECT (d->'properties'->>'wof:id')::bigint AS id,
       d->'properties'->>'src:alt_label'    AS alt,
       d->'properties'                      AS props,
       ST_SetSRID(ST_GeomFromGeoJSON(d->'geometry'), 4326) AS geom
FROM (SELECT pg_read_file(path)::jsonb AS d FROM files) s;

CREATE INDEX ON features (id);
CREATE INDEX ON features USING gist (geom);

CREATE VIEW flights AS
SELECT id,
       props->>'flysfo:flight_number' AS flight_number,
       props->>'flysfo:airline'       AS airline,
       props->>'flysfo:event'         AS event,   -- A = arrival, D = departure
       props->>'flysfo:journey'       AS journey,
       props->>'flysfo:gate'          AS gate,
       (props->>'flysfo:date')::date  AS date,
       to_timestamp(NULLIF((props->>'flysfo:scheduled_timestamp')::bigint, -1)) AS scheduled_at,
       to_timestamp(NULLIF((props->>'flysfo:estimated_timestamp')::bigint, -1)) AS estimated_at,
       to_timestamp(NULLIF((props->>'flysfo:actual_timestamp')::bigint, -1))    AS actual_at,
       geom
FROM features WHERE alt IS NULL;

-- Time-stamped tracks for simulation: array index i of each array matches point i of geom
CREATE VIEW flight_tracks AS
SELECT f.id, f.flight_number, f.journey, f.event, t.alt AS kind, t.geom,
       ARRAY(SELECT to_timestamp(x::bigint) FROM jsonb_array_elements_text(t.props->'swim:timestamps') x) AS times,
       ARRAY(SELECT x FROM jsonb_array_elements_text(coalesce(t.props->'swim:altitudes', t.props->'swim:elevations')) x) AS altitudes,
       ARRAY(SELECT x::int FROM jsonb_array_elements_text(t.props->'swim:speeds') x) AS speeds
FROM features t JOIN flights f USING (id)
WHERE t.alt IS NOT NULL;

SELECT coalesce(alt, 'flight') AS kind, count(*) FROM features GROUP BY 1 ORDER BY 1;
