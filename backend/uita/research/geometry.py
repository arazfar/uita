"""Spherical local east/north tangent approximation centered on KSFO (NM)."""

import math

CENTER = (-122.375, 37.619)
RADIUS_NM = 3440.065


def local(lon, lat):
    return (
        (math.radians(lon - CENTER[0]) * RADIUS_NM * math.cos(math.radians(CENTER[1]))),
        math.radians(lat - CENTER[1]) * RADIUS_NM,
    )


def geographic(x, y):
    return (
        CENTER[0] + math.degrees(x / (RADIUS_NM * math.cos(math.radians(CENTER[1])))),
        CENTER[1] + math.degrees(y / RADIUS_NM),
    )


def heading(dx, dy):
    return math.degrees(math.atan2(dx, dy)) % 360


def closest(a0, a1, b0, b1):
    """Minimum horizontal distance in the part of a one-second segment <1000 ft apart."""
    z = a0["altitude_ft"] - b0["altitude_ft"]
    vz = a1["altitude_ft"] - b1["altitude_ft"] - z
    lo, hi = 0.0, 1.0
    if abs(vz) < 1e-12:
        if abs(z) >= 1000:
            return None
    else:
        bounds = sorted(((-1000 - z) / vz, (1000 - z) / vz))
        lo, hi = max(lo, bounds[0]), min(hi, bounds[1])
        if lo >= hi:
            return None
    dx, dy = a0["x_nm"] - b0["x_nm"], a0["y_nm"] - b0["y_nm"]
    vx = a1["x_nm"] - b1["x_nm"] - dx
    vy = a1["y_nm"] - b1["y_nm"] - dy
    t = (
        max(lo, min(hi, -(dx * vx + dy * vy) / (vx * vx + vy * vy)))
        if vx * vx + vy * vy > 1e-12
        else lo
    )
    return math.hypot(dx + vx * t, dy + vy * t), abs(z + vz * t), t
