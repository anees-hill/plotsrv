# tests/test_watch_errors.py
from __future__ import annotations

from pathlib import Path

import pytest

from plotsrv.runtime import (
    WatchPublishPayload,
    build_watch_read_error_artifact,
    build_watch_publish_error_artifact,
    publish_prepared_watch_payload,
)


def test_build_watch_publish_error_artifact_for_text_log(tmp_path: Path) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello", encoding="utf-8")

    msg = build_watch_publish_error_artifact(
        error=RuntimeError("boom"),
        path=p,
        section="watch",
        label="app",
        artifact_kind="text",
        read_mode="head",
    )

    assert "This watched view could not be updated." in msg
    assert "RuntimeError" not in msg
    assert "boom" not in msg
    assert str(p.resolve()) not in msg
    assert "section=" not in msg
    assert "limits." not in msg


def test_build_watch_publish_error_artifact_for_markdown(tmp_path: Path) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hello", encoding="utf-8")

    msg = build_watch_publish_error_artifact(
        error="bad response",
        path=p,
        section="docs",
        label="readme",
        artifact_kind="markdown",
        read_mode="head",
    )

    assert "This watched view could not be updated." in msg
    assert "bad response" not in msg
    assert str(p.resolve()) not in msg


def test_build_watch_publish_error_artifact_for_csv(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    p.write_text("a\n1\n", encoding="utf-8")

    msg = build_watch_publish_error_artifact(
        error="bad response",
        path=p,
        section="watch",
        label="csv",
        artifact_kind=None,
        read_mode="tail",
    )

    assert "This watched view could not be updated." in msg
    assert "bad response" not in msg
    assert str(p.resolve()) not in msg


def test_build_watch_read_error_artifact_does_not_expose_missing_path(
    tmp_path: Path,
) -> None:
    p = tmp_path / "private.log"

    msg = build_watch_read_error_artifact(
        FileNotFoundError(2, "No such file or directory", str(p.resolve()))
    )

    assert "source file for this view is unavailable" in msg
    assert "FileNotFoundError" not in msg
    assert str(p.resolve()) not in msg


def test_publish_prepared_watch_payload_falls_back_when_primary_returns_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello", encoding="utf-8")

    calls: list[dict[str, object]] = []

    def fake_publish_watch_payload(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        return len(calls) == 2

    monkeypatch.setattr(
        "plotsrv.runtime.publish_watch_payload",
        fake_publish_watch_payload,
    )

    ok = publish_prepared_watch_payload(
        host="127.0.0.1",
        port=8000,
        label="app",
        section="watch",
        payload=WatchPublishPayload(
            kind="artifact",
            artifact="x" * 100,
            artifact_kind="text",
        ),
        path=p,
        read_mode="head",
    )

    assert ok is True
    assert len(calls) == 2

    assert calls[0]["artifact"] == "x" * 100

    assert calls[1]["kind"] == "artifact"
    assert calls[1]["artifact_kind"] == "watch_error"
    assert calls[1]["force"] is True
    assert calls[1]["update_limit_s"] is None
    assert "This watched view could not be updated." in str(calls[1]["artifact"])
    assert str(p.resolve()) not in str(calls[1]["artifact"])


def test_publish_prepared_watch_payload_does_not_recursively_crash_if_fallback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello", encoding="utf-8")

    calls: list[dict[str, object]] = []

    def fake_publish_watch_payload(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        return False

    monkeypatch.setattr(
        "plotsrv.runtime.publish_watch_payload",
        fake_publish_watch_payload,
    )

    ok = publish_prepared_watch_payload(
        host="127.0.0.1",
        port=8000,
        label="app",
        section="watch",
        payload=WatchPublishPayload(
            kind="artifact",
            artifact="x" * 100,
            artifact_kind="text",
        ),
        path=p,
        read_mode="head",
    )

    assert ok is False
    assert len(calls) == 2


def test_watch_publish_error_artifact_kind_is_non_truncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "app.log"
    p.write_text("hello", encoding="utf-8")

    calls: list[dict[str, object]] = []

    def fake_publish_watch_payload(**kwargs: object) -> bool:
        calls.append(dict(kwargs))
        return len(calls) == 2

    monkeypatch.setattr(
        "plotsrv.runtime.publish_watch_payload",
        fake_publish_watch_payload,
    )

    ok = publish_prepared_watch_payload(
        host="127.0.0.1",
        port=8000,
        label="app",
        section="watch",
        payload=WatchPublishPayload(
            kind="artifact",
            artifact="x" * 100,
            artifact_kind="text",
        ),
        path=p,
        read_mode="head",
    )

    assert ok is True
    assert calls[1]["artifact_kind"] == "watch_error"
    assert "This watched view could not be updated." in str(calls[1]["artifact"])
