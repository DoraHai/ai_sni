"""Manual registration and receipt import share destination/source semantics."""
import json
import unicodedata
from pathlib import Path

CONFIG = json.loads(Path(__file__).with_name("backfill_channels.json").read_text(encoding="utf-8"))
CHANNELS = {item["value"] for item in CONFIG["channels"]}
CHANNEL_ALIASES = {alias: item["value"] for item in CONFIG["channels"]
                   for alias in [item["value"], item["label"], *item.get("aliases", [])]}


def validate_custom_name(value):
    rules = CONFIG["custom_name"]
    if not isinstance(value, str):
        raise ValueError(rules["invalid_message"])
    categories = [unicodedata.category(c) for c in value]
    if any(category.startswith(prefix) for category in categories for prefix in rules["forbidden_categories"]):
        raise ValueError(rules["invisible_message"])
    name = value.strip()
    if (not 1 <= len(name) <= rules["max_length"] or not any(
            unicodedata.category(c).startswith(prefix) for c in name for prefix in rules["required_categories"])):
        raise ValueError(rules["invalid_message"])
    return name


def resolve_backfill_source(*, channel, custom_channel_name, source_variant_id, variants):
    by_channel = {v.channel: v for v in variants}
    if channel not in CHANNELS and channel not in by_channel:
        raise ValueError("请选择回填渠道；自定义渠道请选“其他”并填写名称")
    destination = validate_custom_name(custom_channel_name) if channel == "other" else channel
    if source_variant_id is not None:
        variant = next((v for v in variants if v.id == source_variant_id), None)
    else:
        variant = by_channel.get(channel) if channel != "other" else None
    if variant is None:
        raise ValueError("请选择本任务中实际发布的稿件；没有对应渠道稿时请填写来源稿件编号 variant_id")
    return variant, destination, destination if channel == "other" else None
