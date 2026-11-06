"""SFOArrivalEnv-v1: a PortSim-style RL environment over the closed-loop SFO arrival benchmark."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ENV_ID = "SFOArrivalEnv-v1"
