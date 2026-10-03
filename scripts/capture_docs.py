"""Capture the documentation's six scenes from a real, temporary plotsrv server.

uv run --locked --group test python scripts/capture_docs.py
Requires Chromium: uv run --locked --group test playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode

import pandas as pd
from playwright.sync_api import sync_playwright
import requests
import yaml

import plotsrv as ps

ROOT = Path(__file__).resolve().parents[1]


def wait_for(description, check, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except requests.RequestException:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {description}")


def seed(directory: Path, port: int):
    """Use public publishing APIs, real storage, checks, and a live file follower."""
    base = f"http://127.0.0.1:{port}"
    wait_for("server", lambda: requests.get(base + "/views", timeout=2).ok)
    ps.publish_view({"status": "ok", "rows": 123}, label="status", port=port)

    orders = pd.DataFrame({
        "region": ["North", "South", "East", "West"] * 3,
        "week": [1] * 4 + [2] * 4 + [3] * 4,
        "orders": [42, 34, 28, 38, 48, 39, 32, 41, 54, 43, 36, 47],
        "revenue": [5040, 3910, 3500, 4560, 5760, 4485, 4000, 4920, 6480, 4945, 4500, 5640],
    })
    for multiplier in (0.8, 0.9, 1.0):
        version = orders.copy()
        version["orders"] = (version["orders"] * multiplier).round().astype(int)
        ps.publish_view(version, label="orders", section="daily", port=port, force=True)
        expected = {0.8: 1, 0.9: 2, 1.0: 3}[multiplier]
        wait_for("stored orders", lambda: len(requests.get(
            base + "/history/navigation", params={"view": "daily:orders"}, timeout=2
        ).json().get("snapshots", [])) >= expected)

    observed = orders.copy()
    observed.loc[[2, 7], "revenue"] = None
    ps.publish_view(observed, label="order summary", section="daily", observe=True, port=port)
    if not ps.flush_views(timeout=10):
        raise RuntimeError("Observation did not finish")

    # Wait on real check results so the first value establishes a baseline.
    for errors in (0, 3):
        ps.publish_view({"rows": 4821, "errors": errors}, label="import metrics",
                        view_id="daily:metrics", section="daily", port=port, force=True)
        wait_for("check evaluation", lambda: any(
            item.get("observed_value") == errors
            for item in requests.get(base + "/checks", timeout=2).json().get("states", [])
        ))

    source = directory / "job.jsonl"
    source.touch()
    stream = ps.stream_view(source=source, label="job log", section="daily", port=port)
    records = [
        {"level": "INFO", "stage": "read", "message": "Read 4,824 orders", "rows": 4824},
        {"level": "INFO", "stage": "clean", "message": "Removed 3 duplicate rows", "rows": 4821},
        {"level": "WARNING", "stage": "validate", "message": "3 orders need a delivery address", "rows": 3},
        {"level": "ERROR", "stage": "export", "message": "Export paused: fix the missing addresses", "rows": 3},
        {"level": "INFO", "stage": "finish", "message": "Saved valid orders to the staging table", "rows": 4818},
    ]
    with source.open("a", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record) + "\n")
    try:
        wait_for("stream records", lambda: len(requests.get(
            base + "/stream/data", params={"view": "daily:job log"}, timeout=2
        ).json().get("records", [])) == len(records))
    except Exception:
        stream.stop(timeout=2)
        raise
    return stream


def open_view(page, base, view):
    print(f"Opening {view}", flush=True)
    page.goto(base + "/?" + urlencode({"view": view}))
    page.wait_for_function("window.PLOTSRV && PLOTSRV.state.initialViewLoadComplete")
    page.wait_for_function("""PLOTSRV.state.latestStatusPayload &&
        !PLOTSRV.state.statusRefreshPromise && !PLOTSRV.state.viewMenuRefreshPromise""")


def capture_pair(page, output, name):
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme, reduced_motion="reduce")
        page.evaluate("theme => PLOTSRV.core.applyTheme(theme)", theme)
        page.mouse.move(0, 0)
        page.evaluate("""async () => {
            await document.fonts.ready;
            await Promise.all([...document.images].filter(image => image.currentSrc).map(image => image.decode().catch(() => {})));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
        page.screenshot(path=str(output / f"{name}-{theme}.png"), animations="disabled")
    print(f"Captured {name}: light and dark", flush=True)


def capture(base, output):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1080},
                                      device_scale_factor=1, locale="en-GB", timezone_id="UTC",
                                      reduced_motion="reduce")
        page = context.new_page()
        page.set_default_timeout(15_000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.set_viewport_size({"width": 1280, "height": 480})
            open_view(page, base, "default:status")
            assert "123" in page.locator("#artifact-root").inner_text()
            capture_pair(page, output, "status")

            page.set_viewport_size({"width": 1440, "height": 1080})
            open_view(page, base, "daily:orders")
            page.wait_for_function("PLOTSRV.state.tabulatorInstance?.initialized")
            page.click("#table-mode-plot-btn")
            if page.locator("#table-plot-controls-toggle").get_attribute("aria-expanded") == "false":
                page.click("#table-plot-controls-toggle")
            page.select_option("#table-plot-type", "bar")
            page.select_option("#table-plot-category", "region")
            page.select_option("#table-plot-aggregation", "sum")
            page.select_option("#table-plot-value", "orders")
            page.wait_for_selector(".ps-table-plot__svg")
            page.click("#table-save-view-btn")
            page.get_by_label("Name", exact=True).fill("Orders by region")
            page.get_by_label("Caption", exact=True).fill("Three weeks of synthetic orders")
            page.get_by_role("dialog").get_by_role("button", name="Save view", exact=True).click()
            page.wait_for_function("PLOTSRV.core.viewSpec.read().items.length === 1")
            capture_pair(page, output, "table")

            open_view(page, base, "daily:job log")
            page.wait_for_function("PLOTSRV.state.tabulatorInstance?.getData().length === 5")
            page.click("#stream-insights-button")
            page.click("#stream-insights-tab-noteworthy")
            page.wait_for_selector(".ps-stream-noteworthy__item")
            capture_pair(page, output, "stream")

            open_view(page, base, "daily:orders")
            page.click("#snapshot-older")
            page.wait_for_function("PLOTSRV.state.currentSnapshot && !PLOTSRV.state.snapshotNavigation.pending")
            page.click("#snapshot-older")
            page.wait_for_function("!PLOTSRV.state.snapshotNavigation.pending")
            page.click("#compare-enter")
            page.wait_for_function("PLOTSRV.state.compareActive && !PLOTSRV.state.compare.loading")
            capture_pair(page, output, "history")

            open_view(page, base, "daily:order summary")
            page.wait_for_selector("#observation-panel-overview .ps-observation-field-table")
            assert "Missing values were observed" in page.locator("#artifact-root").inner_text()
            capture_pair(page, output, "observation")

            open_view(page, base, "daily:metrics")
            page.click("#header-status-button")
            page.wait_for_function("document.getElementById('status-checks-load').getAttribute('aria-busy') !== 'true'")
            assert "1 active failure" in page.locator("#status-checks-summary").inner_text()
            capture_pair(page, output, "checks")
            if errors:
                raise RuntimeError("Browser errors: " + "; ".join(errors))
        except Exception:
            page.screenshot(path=str(output / "capture-failure.png"), full_page=True)
            print(page.url, page.locator("body").inner_text()[:4000], flush=True)
            raise
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/assets/images/screenshots")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # This process must not use a contributor's server, credentials, or config.
    for name in list(os.environ):
        if name.startswith("PLOTSRV_"):
            del os.environ[name]
    with TemporaryDirectory(prefix="plotsrv-docs-") as scratch:
        directory = Path(scratch)
        config = directory / "plotsrv.yml"
        config.write_text(yaml.safe_dump({
            "storage-settings": {"enabled": True, "root_dir": str(directory / "store"), "default_keep_last": 5,
                                 "views": {"default:status": {"enabled": False}}},
            "freshness-settings": {"enabled": True, "expected_every": "1h", "warn_after": "90m", "overdue_after": "2h"},
            "stream-settings": {"heartbeat_interval_s": 0.25},
            "checks-settings": {"rules": [{"id": "import-errors", "name": "Import errors", "source": "daily:metrics",
                "kind": "state", "path": ["errors"], "op": "gt", "value": 0, "severity": "warning"}]},
        }))
        os.environ["PLOTSRV_CONFIG"] = str(config)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        stream = None
        try:
            ps.start_server(port=port, config=config, auto_on_show=False)
            stream = seed(directory, port)
            capture(f"http://127.0.0.1:{port}", args.output)
        finally:
            if stream is not None:
                stream.stop(timeout=2)
            ps.stop_server(join=True)


if __name__ == "__main__":
    main()
