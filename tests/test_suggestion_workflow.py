import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.suggestions import SuggestionWorkflowRequest, _effective_handling_status


def test_terminal_suggestion_status_wins_over_internal_workflow_status():
    adopted = SimpleNamespace(status="adopted", handling_status="waiting_writeback")
    ignored = SimpleNamespace(status="ignored", handling_status="in_progress")
    pending = SimpleNamespace(status="pending", handling_status="in_progress")

    assert _effective_handling_status(adopted) == "completed"
    assert _effective_handling_status(ignored) == "rejected"
    assert _effective_handling_status(pending) == "in_progress"


def test_workflow_request_supports_clearing_assignment_and_deadline():
    req = SuggestionWorkflowRequest(clear_assignee=True, clear_due_at=True, handling_status="todo")
    assert req.clear_assignee is True
    assert req.clear_due_at is True
    assert req.handling_status == "todo"


def test_workflow_terminal_states_are_explicitly_supported():
    assert SuggestionWorkflowRequest(handling_status="completed").handling_status == "completed"
    assert SuggestionWorkflowRequest(handling_status="rejected").handling_status == "rejected"
