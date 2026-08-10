"""robots.txt AI crawler UA audit."""

from __future__ import annotations

import unittest

from app.geo.audit import parse_robots_ai_agents


class RobotsAiAgentsTests(unittest.TestCase):
    def test_blocks_gptbot_root(self):
        text = """
User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /
"""
        out = parse_robots_ai_agents(text)
        gpt = next(a for a in out["agents"] if a["ua"] == "GPTBot")
        self.assertEqual(gpt["status"], "blocked")
        self.assertGreaterEqual(out["blocked_count"], 1)

    def test_unspecified_when_only_star_allow(self):
        text = """
User-agent: *
Allow: /
"""
        out = parse_robots_ai_agents(text)
        claude = next(a for a in out["agents"] if a["ua"] == "ClaudeBot")
        self.assertEqual(claude["status"], "unspecified")


if __name__ == "__main__":
    unittest.main()
