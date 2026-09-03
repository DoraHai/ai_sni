"""Pure local recording tests: synthetic Chinese only, no model calls."""
import json
import os
import subprocess
import sys

import pytest

from scripts.sem_expansion_eval_record import encode_record, save_record, REPOSITORY


def record():
    return dict(source_commit="a" * 40, model="offline-mock", system_sha256="b" * 64,
                user_sha256="c" * 64, observed_at="2026-09-03T00:00:00+08:00",
                model_output='{"items":[{"word":"中文涂料 ¥13.27 🐯","reason":"含\\n换行和引号\\\""}]}')


def test_ascii_json_preserves_exact_model_text_including_malformed_json():
    for raw in (record()["model_output"], '{"items": [中文未闭合', '中文\n"引号"\\反斜线', '', ' \n\t '):
        sample = {**record(), "model_output": raw}
        data = encode_record(sample)
        assert data.isascii() and json.loads(data.decode("utf-8")) == sample


@pytest.mark.parametrize("change", [{"Authorization": "SYNTHETIC_SECRET_MARKER"},
    {"headers": {}}, {"source_commit": "short"}, {"system_sha256": "z" * 64},
    {"model_output": None}])
def test_metadata_rejects_unexpected_or_invalid_fields(change):
    with pytest.raises(ValueError):
        encode_record({**record(), **change})


def test_save_is_lossless_exclusive_and_does_not_mutate_input(tmp_path):
    sample = record()
    target = tmp_path / "observation.json"
    save_record(sample, target)
    assert json.loads(target.read_bytes()) == sample
    with pytest.raises(FileExistsError):
        save_record({**sample, "model_output": "different"}, target)
    assert json.loads(target.read_bytes()) == sample


def test_repository_output_is_rejected():
    with pytest.raises(ValueError, match="outside"):
        save_record(record(), REPOSITORY / "model-observation.json")


def test_cli_under_ascii_console_preserves_chinese_and_only_prints_summary(tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "result.json"
    source.write_text(json.dumps(record(), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run([sys.executable, str(REPOSITORY / "scripts/sem_expansion_eval_record.py"),
                             "--input", str(source), "--output", str(output)],
                            env={**os.environ, "PYTHONIOENCODING": "ascii"}, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.isascii() and b"offline-mock" not in result.stdout
    assert json.loads(output.read_bytes()) == record()


def test_cli_failure_does_not_print_sensitive_input(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"Authorization":"SYNTHETIC_SECRET_MARKER"}', encoding="utf-8")
    result = subprocess.run([sys.executable, str(REPOSITORY / "scripts/sem_expansion_eval_record.py"),
                             "--input", str(source), "--output", str(tmp_path / "not-created.json")],
                            capture_output=True)
    assert result.returncode == 1
    assert b"SYNTHETIC_SECRET_MARKER" not in result.stdout + result.stderr
    assert not (tmp_path / "not-created.json").exists()
