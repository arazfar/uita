#!/bin/sh
# Loads the SFO Museum flight GeoJSON into PostGIS. Safe to re-run (drops and reloads).
set -e
cd "$(dirname "$0")"
docker compose up -d --wait
docker compose exec -T db sh -c 'find /data -name "*.geojson" > /tmp/files.txt && wc -l < /tmp/files.txt'
docker compose exec -T db psql -U postgres -d flights < load.sql
