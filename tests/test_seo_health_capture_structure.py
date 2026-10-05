"""Regression: /health/seo must read capture constraints from a real CursorResult.

SQLAlchemy's CursorResult exposes keys() without __getitem__, so dict(result)
treats it as a mapping and fails. Production revision 0104 hit this on 2026-10-05.
"""
import asyncio

from app import seo_main


class _CursorLikeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def keys(self):  # mapping trap, like sqlalchemy CursorResult
        return ["name", "definition"]

    def all(self):
        return list(self._rows)

    def scalars(self):
        return iter([row[0] for row in self._rows])


class _Conn:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)


def test_capture_structure_accepts_cursor_like_results():
    columns = [(name, kind, not_null) for name, (kind, not_null) in seo_main.SEO_CAPTURE_COLUMNS.items()]
    conn = _Conn([
        _CursorLikeResult(columns),
        _CursorLikeResult([("CHECK (status IN ('pending', 'running', 'succeeded', 'failed'))",)]),
        _CursorLikeResult([
            ("ck_seo_page_captures_source", "CHECK (source IN ('auto', 'manual'))"),
            ("ck_seo_page_captures_manual_upload", "CHECK (source <> 'manual' OR (uploaded_by IS NOT NULL AND uploaded_at IS NOT NULL))"),
        ]),
    ])
    asyncio.run(seo_main._check_capture_structure(conn))