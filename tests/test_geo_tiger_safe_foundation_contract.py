import json
from pathlib import Path

from app.geo.content.schemas import (
    OptimizationBusinessCreate,
    PromptCreate,
    PublishingChannelCreate,
)


FIXTURE = (
    Path(__file__).parents[1]
    / "integrations"
    / "geo-workbench"
    / "tiger-safe-foundation.synthetic.json"
)


def test_tiger_safe_foundation_payloads_match_the_production_schemas():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    creates = data["creates"]

    business = OptimizationBusinessCreate.model_validate(
        creates["optimization_business"]
    )
    prompts = [PromptCreate.model_validate(row) for row in creates["prompts"]]
    channel = PublishingChannelCreate.model_validate(creates["publishing_channel"])

    assert business.tenant_id == data["tenant_id"] == 4
    assert len(prompts) == 3
    assert all(row.tenant_id == 4 and row.unit_id is None for row in prompts)
    assert channel.tenant_id == 4
    assert channel.publish_mode == "manual_only"
    assert channel.enabled is False


def test_tiger_safe_foundation_has_no_executable_or_secret_material():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = FIXTURE.read_text(encoding="utf-8").lower()

    assert set(data["creates"]) == {
        "optimization_business",
        "prompts",
        "publishing_channel",
    }
    assert "authorization" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert "token" not in raw
