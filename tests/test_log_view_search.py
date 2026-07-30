"""Search matches the full untruncated event text, not just the display
description (issue #60)."""

from dlab.tui.models import LogEvent
from dlab.tui.widgets.log_view import LogView


def _dlab_start_with_prompt(prompt: str) -> LogEvent:
    return LogEvent.from_raw(
        {"type": "dlab_start", "timestamp": 1, "model": "m/x",
         "agent": "main", "prompt": prompt},
        source="main",
    )


def test_full_description_holds_prompt_but_short_description_does_not() -> None:
    ev = _dlab_start_with_prompt("analyze the ZEBRA revenue dataset")
    assert "ZEBRA" not in ev.description       # trimmed for display
    assert "ZEBRA" in ev.full_description       # available in full text


def test_search_finds_term_only_in_full_description() -> None:
    lv = LogView()
    lv._events = [
        _dlab_start_with_prompt("analyze the ZEBRA revenue dataset"),
        _dlab_start_with_prompt("nothing relevant here"),
    ]
    matches = lv.highlight_search("zebra")
    assert matches == [0]


def test_search_no_match_returns_empty() -> None:
    lv = LogView()
    lv._events = [_dlab_start_with_prompt("plain prompt")]
    assert lv.highlight_search("giraffe") == []
