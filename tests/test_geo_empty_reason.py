"""Empty-state diagnosis is a frontend helper; keep the priority contract here too."""

from __future__ import annotations

import unittest


# Mirror frontend/src/utils/geoEmptyReason.js priority so product copy cannot drift silently.
def diagnose(engine_count=0, enabled=0, patrol=False, last_run=None, snaps=0, mentions=None):
    if engine_count <= 0 or enabled <= 0:
        return "no_engine"
    if not patrol and snaps <= 0:
        return "patrol_off"
    if snaps <= 0 and not last_run:
        return "not_run"
    if snaps <= 0 and last_run:
        return "ran_empty"
    if mentions is not None and snaps > 0 and mentions <= 0:
        return "no_mention"
    return None


class EmptyReasonTests(unittest.TestCase):
    def test_priority(self):
        self.assertEqual(diagnose(), "no_engine")
        self.assertEqual(diagnose(engine_count=3, enabled=0), "no_engine")
        self.assertEqual(diagnose(engine_count=3, enabled=2, patrol=False), "patrol_off")
        self.assertEqual(
            diagnose(engine_count=3, enabled=2, patrol=True, snaps=0),
            "not_run",
        )
        self.assertEqual(
            diagnose(engine_count=3, enabled=2, patrol=True, last_run="x", snaps=0),
            "ran_empty",
        )
        self.assertEqual(
            diagnose(engine_count=3, enabled=2, patrol=True, last_run="x", snaps=8, mentions=0),
            "no_mention",
        )
        self.assertIsNone(
            diagnose(engine_count=3, enabled=2, patrol=True, last_run="x", snaps=8, mentions=3)
        )


if __name__ == "__main__":
    unittest.main()
