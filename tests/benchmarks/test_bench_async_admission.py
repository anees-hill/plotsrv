from __future__ import annotations

import pandas as pd

from plotsrv.publisher import _estimate_publish_task_bytes


def test_async_dataframe_estimate_does_not_deep_scan(
    monkeypatch,
) -> None:
    df = pd.DataFrame({"id": range(100), "text": ["value"] * 100})
    calls: list[bool] = []
    real = pd.DataFrame.memory_usage

    def checked_memory_usage(self, *args, **kwargs):
        calls.append(bool(kwargs.get("deep", False)))
        if kwargs.get("deep"):
            raise AssertionError("async queue admission must not deep-scan values")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "memory_usage", checked_memory_usage)

    assert _estimate_publish_task_bytes(df) > 0
    assert calls == [False]
