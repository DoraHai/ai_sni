"""Source-only fact verification; project/commit checks stay in the shared guard."""
from app.security.advisor_scope import deny


FACT_VERIFY_SUFFIX = "/facts/{fact_id}/verify"
FACT_VERIFY_FIELDS = (
    "excerpt excerpt_locator source_url note "
    "expected_source_statement expected_source_name expected_source_url"
)


def check_fact_verify_fields(body: dict) -> None:
    # Require an explicit source in the request, even if the fact has one.
    # The existing handler compares the source-name snapshot with the locked row.
    for key in ("source_url", "expected_source_name"):
        if not isinstance(body.get(key), str) or not body[key].strip():
            deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "核验前请填写来源名称和来源链接")
