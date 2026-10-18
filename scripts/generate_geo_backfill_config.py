"""Generate the browser copy; edit app/geo/content/backfill_channels.json only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "app/geo/content/backfill_channels.json"
    target = ROOT / "frontend/src/utils/geoBackfillConfig.json"
    target.write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
