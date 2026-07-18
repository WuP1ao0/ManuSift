"""Stream fold must not re-concatenate provider snapshots."""
from __future__ import annotations

from manusift.llm.chat import ChatResponse, fold_stream_chunk


def _t(text: str, stop: str = "") -> ChatResponse:
    return ChatResponse(
        content_blocks=[{"type": "text", "text": text}],
        stop_reason=stop,
    )


def test_snapshot_stream_does_not_duplicate():
    """DeepSeek/Anthropic-style: each yield is full text so far."""
    snaps = [
        "论文",
        "论文 clean",
        "论文 clean_academic.pdf",
        "论文 clean_academic.pdf 已加载，我可以开始工作。",
    ]
    acc = None
    longest = ""
    for s in snaps:
        acc, longest = fold_stream_chunk(acc, _t(s), longest_text=longest)
    assert acc is not None
    assert acc.text == snaps[-1]
    assert "论文论文" not in acc.text


def test_genuine_delta_stream_still_concatenates():
    acc = None
    longest = ""
    for s in ["Hel", "lo", "!"]:
        acc, longest = fold_stream_chunk(acc, _t(s), longest_text=longest)
    assert acc is not None
    assert acc.text == "Hello!"


def test_stop_reason_carried_on_empty_delta():
    acc, longest = fold_stream_chunk(None, _t("hi"), longest_text="")
    acc, longest = fold_stream_chunk(
        acc,
        ChatResponse(content_blocks=[], stop_reason="end_turn"),
        longest_text=longest,
    )
    assert acc.text == "hi"
    assert acc.stop_reason == "end_turn"
