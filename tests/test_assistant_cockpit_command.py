from app.ai.assistant import sanitize_cockpit_command


def test_cockpit_command_only_keeps_visible_targets():
    command = sanitize_cockpit_command(
        {
            "answer": "  先看异常花费。 ",
            "filters": {"modules": ["sem", "admin", "geo"]},
            "highlight": {"ids": ["sem-cost", "secret-row"]},
            "focus_module": "admin",
            "drawer_metric_id": "secret-row",
            "actions": [
                {"label": "看花费", "type": "open-metric", "target": "sem-cost"},
                {"label": "直接调价", "type": "sem.bid", "target": "sem-cost"},
                {"label": "越权打开", "type": "open-module", "target": "admin"},
            ],
        },
        allowed_metric_ids={"sem-cost"},
        allowed_modules={"sem", "geo"},
    )

    assert command["answer"] == "先看异常花费。"
    assert command["filters"] == {"modules": ["sem", "geo"]}
    assert command["highlight"]["ids"] == ["sem-cost"]
    assert command["focus_module"] == "all"
    assert command["drawer_metric_id"] == "sem-cost"
    assert command["actions"] == [
        {"label": "看花费", "type": "open-metric", "target": "sem-cost"}
    ]


def test_cockpit_command_accepts_all_and_never_creates_a_write_action():
    command = sanitize_cockpit_command(
        {
            "focus_module": "all",
            "actions": [
                {"label": "恢复全域", "type": "reset-view", "target": ""},
                {"label": "发布", "type": "publish", "target": "geo"},
            ],
        },
        allowed_metric_ids=set(),
        allowed_modules={"geo"},
    )

    assert command["focus_module"] == "all"
    assert command["actions"] == [
        {"label": "恢复全域", "type": "reset-view", "target": ""}
    ]
