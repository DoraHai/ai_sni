"""Safe cleanup for a small set of corrupted legacy local demo labels."""

from __future__ import annotations

import re


_CORRUPTED_TASK_TITLE = "[???] ????????"
_CORRUPTED_FACT = re.compile(r"^\?\?\?\?([1-3])$")
_CORRUPTED_DEMO_SOURCE = re.compile(r"^(?:demo-source|seed)-([1-3])$")
_CORRUPTED_FACT_STATEMENT = re.compile(r"^[?\s]+([1-3])$")


def clean_legacy_demo_task(title: str, record_id: int) -> str:
    """Replace the exact old task placeholder without touching normal content."""
    if title == _CORRUPTED_TASK_TITLE:
        return f"历史演示内容任务 {record_id}"
    return title


def clean_legacy_demo_fact(title: str, source_name: str) -> str:
    """Replace only matching corrupted fact/source pairs from the old demo seed."""
    title_match = _CORRUPTED_FACT.fullmatch(title or "")
    source_match = _CORRUPTED_DEMO_SOURCE.fullmatch(source_name or "")
    if title_match and source_match and title_match.group(1) == source_match.group(1):
        return f"历史演示事实 {title_match.group(1)}"
    return title


def clean_legacy_demo_fact_statement(statement: str, source_name: str) -> str:
    """Replace only question-mark statements paired with the old demo sources."""
    statement_match = _CORRUPTED_FACT_STATEMENT.fullmatch(statement or "")
    source_match = _CORRUPTED_DEMO_SOURCE.fullmatch(source_name or "")
    if statement_match and source_match and statement_match.group(1) == source_match.group(1):
        return "历史演示数据，供本地界面测试使用。"
    return statement
