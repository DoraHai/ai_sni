"""Lossless offline SEM model-output recording; no network or credential access.

Call save_record immediately after receiving model message content and before
printing it. Never pass request headers, credentials or the whole HTTP exchange.
The CLI re-encodes an existing UTF-8 JSON record, not a model API request.
"""
import argparse
import json
from pathlib import Path
import re


FIELDS = {"source_commit", "model", "system_sha256", "user_sha256", "observed_at", "model_output"}
REPOSITORY = Path(__file__).resolve().parents[1]


def encode_record(record: dict) -> bytes:
    """ASCII JSON is valid UTF-8 and round-trips Chinese even on legacy consoles.

    model_output is the original message string, not repaired/reconstructed JSON.
    It may contain invalid model JSON; preserve that evidence without retrying.
    Whitelisted metadata prevents accidentally serializing an HTTP client config.
    This is not a content-redaction engine: inputs must contain no credentials.
    """
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("Invalid record fields; HTTP metadata and credentials are not accepted")
    if any(not isinstance(value, str) or (field != "model_output" and not value.strip())
           for field, value in record.items()):
        raise ValueError("Record fields must be strings; metadata must be nonempty")
    for field, length in (("source_commit", 40), ("system_sha256", 64), ("user_sha256", 64)):
        if not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", record[field]):
            raise ValueError("Invalid provenance hash")
    return (json.dumps(record, ensure_ascii=True, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")


def save_record(record: dict, destination: Path) -> None:
    data = encode_record(record)
    target = Path(destination)
    if target.is_symlink():
        raise ValueError("Record destination must not be a symbolic link")
    target = target.resolve()
    if target.is_relative_to(REPOSITORY):
        raise ValueError("Keep model observations outside the repository")
    # Exclusive creation: never silently replace an earlier observation.
    with target.open("xb") as stream:
        stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        record = json.loads(args.input.read_text(encoding="utf-8-sig"))
        save_record(record, args.output)
    except (OSError, ValueError):
        # Never print input contents or exception payloads.
        print("Record not saved: check format, hashes and a new output path outside the repository.")
        return 1
    print("Record saved. No model request or deployment performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
