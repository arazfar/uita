#!/usr/bin/env python3
"""Find observed ADSB.lol backfill candidates without changing the replay.

Read local readsb trace files or stream concatenated daily tar parts. Output is
a review artifact, not a replacement for the complete airport-operation roster.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import tarfile

HERE = Path(__file__).resolve().parent
SOURCE = "https://github.com/adsblol/globe_history_2026"
FORMAT = "https://github.com/wiedehopf/readsb/blob/dev/README-json.md#trace-jsons"
SFO = (37.6213, -122.3790)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def registration(value):
    return re.sub(r"[\s-]", "", str(value or "")).upper()


def distance_nm(lat, lon):
    p1, p2 = math.radians(SFO[0]), math.radians(lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon - SFO[1]) / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(h)))


def load_operations(include_covered):
    """Use the same source rosters as build_web_data.py; never invent operations."""
    by_reg, by_hex = defaultdict(list), defaultdict(list)
    missing = 0
    for kind, folder, name, time_key in (
        ("arr", "bundle", "arrivals.json", "arrival_operation_time_utc"),
        ("dep", "departures-bundle", "departures.json", "departure_operation_time_utc"),
    ):
        root = HERE / folder
        covered = {t["operation_id"] for t in json.loads((root / "tracks.json").read_text())["tracks"] if len(t["points"]) >= 2}
        for item in json.loads((root / name).read_text()):
            op = dict(id=item["operation_id"], kind=kind,
                      t=datetime.fromisoformat(item[time_key]).timestamp(),
                      reg=registration(item.get("registration")),
                      eligible=include_covered or item["operation_id"] not in covered)
            missing += int(op["eligible"])
            if op["reg"]:
                by_reg[op["reg"]].append(op)
            # Current source rosters have registration only. An explicit ICAO
            # address may be used when a future source supplies it; never derive
            # an aircraft identity from callsign alone.
            hex_id = str(item.get("icao24") or item.get("icao_hex") or "").lower()
            if re.fullmatch(r"[0-9a-f]{6}", hex_id):
                by_hex[hex_id].append(op)
    return by_reg, by_hex, missing


class Parts(io.RawIOBase):
    """Present split tar parts as one stream without another multi-GB copy."""
    def __init__(self, handles):
        self.handles = iter(handles)
        self.current = next(self.handles, None)
        self.bytes_read = 0
        self.last_nonzero = -1

    def readable(self):
        return True

    def readinto(self, target):
        while self.current is not None:
            count = self.current.readinto(target)
            if count:
                nonzero_end = len(bytes(target[:count]).rstrip(b"\x00"))
                if nonzero_end:
                    self.last_nonzero = self.bytes_read + nonzero_end - 1
                self.bytes_read += count
                return count
            self.current = next(self.handles, None)
        return 0


def normalized_points(doc):
    """Retain observed samples and altitude reference; do not interpolate."""
    base = doc.get("timestamp")
    if not number(base) or not isinstance(doc.get("trace"), list):
        raise ValueError("Expected a readsb trace with numeric timestamp and trace array")
    points = []
    for raw in doc["trace"]:
        if len(raw) < 7 or not all(number(x) for x in raw[:3]):
            continue
        offset, lat, lon, altitude, speed, _, flags = raw[:7]
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not isinstance(flags, int):
            continue
        # Bit 1 marks stale positions; bit 8 marks geometric altitude. Bit 4
        # describes vertical-rate reference, so it does not null altitude.
        # The compact tuple cannot describe reference; keep flags separately.
        if flags & 1:
            continue
        altitude_ft = altitude if number(altitude) and not flags & 8 else None
        points.append(dict(t=base + offset, lat=lat, lon=lon, alt=altitude_ft,
                           gs=speed if number(speed) else None,
                           ground=altitude == "ground", flags=flags))
    return sorted(points, key=lambda p: p["t"])


def consider(doc, source, by_reg, by_hex, candidates, stats):
    hex_id = str(doc.get("icao", "")).lower()
    reg = registration(doc.get("r"))
    if not re.fullmatch(r"~?[0-9a-f]{6}", hex_id):
        raise ValueError(f"Invalid ICAO/source address in {source['member']}")
    operations = {o["id"]: o for o in by_reg.get(reg, [])}
    operations.update({o["id"]: o for o in by_hex.get(hex_id, [])})
    points = normalized_points(doc)
    stats["observed_points_read"] += len(points)
    for op in operations.values():
        if not op["eligible"]:
            continue
        # An identity match is insufficient: require a received low/ground
        # point near SFO within 15 minutes of the roster's operation time.
        near = [p for p in points if abs(p["t"] - op["t"]) <= 900
                and (p["ground"] or p["alt"] is not None and p["alt"] <= 1000)
                and distance_nm(p["lat"], p["lon"]) <= 3]
        if not near:
            continue
        evidence = min(near, key=lambda p: abs(p["t"] - op["t"]))
        lo, hi = ((op["t"] - 5400, op["t"] + 600) if op["kind"] == "arr"
                  else (op["t"] - 600, op["t"] + 5400))
        # Bound the candidate at the midpoint to adjacent roster movements of
        # this same aircraft. A daily trace can contain many separate flights.
        peers = {o["id"]: o for o in by_reg.get(reg, []) + by_hex.get(hex_id, [])}
        for other in peers.values():
            if other["t"] < op["t"]:
                lo = max(lo, (other["t"] + op["t"]) / 2)
            elif other["t"] > op["t"]:
                hi = min(hi, (other["t"] + op["t"]) / 2)
        retained = [p for p in points if lo <= p["t"] <= hi and distance_nm(p["lat"], p["lon"]) <= 80]
        if len(retained) < 2:
            continue
        key = (op["id"], hex_id)
        item = candidates.setdefault(key, dict(operation_id=op["id"], kind=op["kind"],
                icao24=hex_id, registration=doc.get("r"), operation_time_utc=op["t"],
                match_method="identity_airport_time", source_files=[], observations=[],
                airport_evidence_time_utc=evidence["t"]))
        item["source_files"].append(source)
        item["observations"].extend(retained)
        if abs(evidence["t"] - op["t"]) < abs(item["airport_evidence_time_utc"] - op["t"]):
            item["airport_evidence_time_utc"] = evidence["t"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--archive", nargs="+", help="Ordered local tar parts; use - for concatenated stdin")
    inputs.add_argument("--trace-directory", type=Path, help="Directory of original readsb .json/.json.gz traces")
    parser.add_argument("--release", required=True, help="Canonical ADSB.lol daily release tag for provenance")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true", help="Write an explicitly incomplete archive sample")
    parser.add_argument("--include-covered", action="store_true", help="Also report candidates for operations which already have Museum paths")
    args = parser.parse_args()
    if not re.fullmatch(r"v\d{4}\.\d{2}\.\d{2}-planes-readsb-(?:prod|staging)-\d+", args.release):
        parser.error("Expected a daily prod/staging release tag, such as v2026.08.03-planes-readsb-prod-0")
    by_reg, by_hex, operation_count = load_operations(args.include_covered)
    candidates, stats = {}, defaultdict(int)
    complete, scan_error = False, None

    def consume(name, content):
        doc = json.loads(gzip.decompress(content) if content[:2] == b"\x1f\x8b" else content)
        if not isinstance(doc, dict) or "trace" not in doc:
            return
        source = dict(member=name, sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
        stats["trace_files_scanned"] += 1
        consider(doc, source, by_reg, by_hex, candidates, stats)

    if args.trace_directory:
        paths = sorted(set(args.trace_directory.rglob("*.json")) | set(args.trace_directory.rglob("*.json.gz")))
        for path in paths:
            consume(str(path.relative_to(args.trace_directory)), path.read_bytes())
    else:
        if "-" in args.archive and args.archive != ["-"]:
            parser.error("Use stdin alone, or an ordered list of local archive parts")
        with ExitStack() as stack:
            handles = [sys.stdin.buffer] if args.archive == ["-"] else [stack.enter_context(open(p, "rb")) for p in args.archive]
            joined = Parts(handles)
            stream = io.BufferedReader(joined)
            try:
                last_member_end = 0
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    for member in archive:
                        last_member_end = member.offset_data + ((member.size + 511) // 512) * 512
                        if member.isfile() and "/traces/" in "/" + member.name and "trace_full_" in member.name:
                            consume(member.name, archive.extractfile(member).read())
                # tarfile stops at the first end marker. Consume every supplied
                # part and reject hidden trailing data, including buffered bytes.
                while stream.read(1024 * 1024):
                    pass
                if joined.bytes_read < last_member_end + 1024 or joined.last_nonzero >= last_member_end:
                    raise tarfile.ReadError("Missing tar end markers or nonzero trailing data")
                complete = True
            except (tarfile.ReadError, EOFError) as error:
                if not args.allow_partial:
                    raise ValueError("Incomplete archive; concatenate every part, or use --allow-partial for a labelled sample") from error
                scan_error = str(error)

    identities = defaultdict(set)
    for operation_id, hex_id in candidates:
        identities[operation_id].add(hex_id)
    output = []
    for (operation_id, _), candidate in sorted(candidates.items()):
        if len(identities[operation_id]) != 1:
            continue
        observations = {p["t"]: p for p in candidate.pop("observations")}
        observations = [observations[t] for t in sorted(observations)]
        candidate["points"] = [[p["t"], p["lon"], p["lat"], p["alt"], p["gs"]] for p in observations]
        candidate["point_flags"] = [p["flags"] for p in observations]
        candidate["on_ground"] = [p["ground"] for p in observations]
        output.append(candidate)
    if not stats["trace_files_scanned"]:
        raise ValueError("No original readsb traces found; inspect input layout")
    result = dict(source=SOURCE, release=SOURCE + "/releases/tag/" + args.release,
        format=FORMAT, license="ODbL-1.0", license_url="https://opendatacommons.org/licenses/odbl/1-0/", mode="review_candidates_only",
        archive_scan_complete=complete, scan_error=scan_error,
        generated_at=datetime.now(timezone.utc).isoformat(),
        point_columns=["timestamp_unix_utc", "longitude", "latitude", "barometric_altitude_ft_or_null", "groundspeed_kt_or_null"],
        limits=["No replay files changed", "Identity/time/airport matches require review", "No coverage claim before complete extraction and review", "No interpolated points; stale positions excluded; ground and geometric altitudes remain null"],
        summary=dict(stats, roster_operations_considered=operation_count, candidate_operations=len(output),
                     ambiguous_operations=sum(len(v) > 1 for v in identities.values())), candidates=output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps({k: result[k] for k in ("archive_scan_complete", "scan_error", "summary")}))


if __name__ == "__main__":
    main()
