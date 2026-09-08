import json

import pytest

from waketrace.engine import WakeProtocolError, parse_final_draft


def payload(**overrides):
    data = {
        "outcome": "trace",
        "fact": "A small event happened.",
        "content": "A private account.",
        "share": "",
        "residue": "",
        "next_wake": {"min_minutes": 30, "max_minutes": 60, "reason": "later"},
    }
    data.update(overrides)
    return json.dumps(data)


def test_parses_valid_trace():
    result = parse_final_draft(payload())
    assert result.outcome == "trace"
    assert result.next_min_minutes == 30


def test_message_requires_share():
    with pytest.raises(WakeProtocolError, match="message_without_share"):
        parse_final_draft(payload(outcome="message", share=""))


def test_silence_is_explicit_not_empty_response():
    with pytest.raises(WakeProtocolError, match="not_json"):
        parse_final_draft("")
    result = parse_final_draft(payload(outcome="silent", fact="", content=""))
    assert result.outcome == "silent"

