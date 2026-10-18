"""Explicit migration/data installation entrypoint for hosted release jobs."""

import subprocess
import sys


def main():
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "uita.research.cli", "bootstrap"], check=True)
    print("Research migrations and checksummed demo bootstrap completed", flush=True)


if __name__ == "__main__":
    main()
