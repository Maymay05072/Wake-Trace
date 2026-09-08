from waketrace.cli import render_timeline


def test_render_timeline_without_a_frontend():
    output = render_timeline(
        [
            {
                "created_at": "2026-09-08T10:00:00+00:00",
                "outcome": "trace",
                "trigger_kind": "weather",
                "fact": "窗外开始下雨。",
                "content": "在窗边听了一会儿雨。",
                "share": "",
            }
        ]
    )

    assert "trace · weather" in output
    assert "事实：窗外开始下雨。" in output
    assert "经历：在窗边听了一会儿雨。" in output
    assert "想说" not in output


def test_render_empty_timeline():
    assert render_timeline([]) == "还没有自主醒来记录。"
