"""The score must never turn synthetic passes, missing reviews or violations green."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("qualification", Path(__file__).parents[1] / "scripts/automation_qualification.py")
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class QualificationTest(unittest.TestCase):
    def review(self):
        return {"reviewer": "test-reviewer", "notes": "核对了每个来源、数字、页面目标和人工审批边界。",
                "scores": dict(qualification.DIMENSIONS), "critical_findings": []}

    def score(self, review, accepted=True, source="recorded_provider_response"):
        return qualification.human_score(review, accepted=accepted, source_kind=source)

    def test_no_review_never_receives_a_model_score(self):
        self.assertEqual(self.score(None), {"score": None, "decision": "human_review_pending"})

    def test_synthetic_fixture_never_receives_a_model_score(self):
        self.assertIsNone(self.score(self.review(), source="synthetic_guard_fixture")["score"])

    def test_validator_rejection_overrides_perfect_human_score(self):
        self.assertEqual(self.score(self.review(), accepted=False)["decision"], "automatic_gate_rejected")

    def test_each_critical_violation_overrides_total(self):
        for flag in qualification.CRITICAL:
            with self.subTest(flag=flag):
                review = self.review(); review["critical_findings"] = [flag]
                self.assertEqual(self.score(review)["decision"], "critical_rejected")

    def test_threshold_uses_all_five_dimensions(self):
        review = self.review(); review["scores"]["facts"] = 15
        self.assertEqual(self.score(review)["decision"], "business_review_passed")
        review["scores"]["facts"] = 14
        self.assertEqual(self.score(review)["decision"], "business_review_failed")

    def test_partial_boolean_extra_or_out_of_range_scores_are_rejected(self):
        for change in ("partial", "boolean", "extra", "overflow"):
            review = self.review()
            if change == "partial": del review["scores"]["focus"]
            if change == "boolean": review["scores"]["focus"] = True
            if change == "extra": review["scores"]["model"] = 100
            if change == "overflow": review["scores"]["focus"] = 21
            with self.subTest(change=change), self.assertRaises(ValueError): self.score(review)

    def test_review_requires_person_and_evidence_notes(self):
        for key, value in (("reviewer", ""), ("notes", "通过")):
            review = self.review(); review[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.score(review)

    def test_completion_claims_are_separate_from_advisory_text(self):
        self.assertTrue(qualification.COMPLETION.search("本方案已发布并完成官网验收"))
        self.assertFalse(qualification.COMPLETION.search("建议人工审核后实施方案，当前仍是草稿。"))


if __name__ == "__main__":
    unittest.main()
