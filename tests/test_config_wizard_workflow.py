from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
import yaml

pytest.importorskip("textual")
from textual.widgets import Input, Select, Static
from plotsrv import settings
from plotsrv.config_wizard.draft import Draft
from plotsrv.config_wizard.tui import ConfigWizard


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    import requests, urllib.request

    def no_network(*a, **kw):
        pytest.fail("No remote calls during configuration")

    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)


async def button(pilot, app, key):
    for _ in range(100):
        if app.focused and app.focused.id == key:
            break
        await pilot.press("tab")
    assert app.focused.id == key
    await pilot.press("enter")


async def finish(pilot, app):
    assert app.stage == "ready"
    await button(pilot, app, "review-path")
    assert app.stage == "save_path"
    await button(pilot, app, "next")
    assert app.stage == "review", str(app.screen.query_one("#error", Static).content)
    path = app.review.path
    before = path.read_bytes() if path.exists() else None
    await button(pilot, app, "save-reviewed")
    assert app.screen.__class__.__name__ == "SaveConfirmation"
    assert (path.read_bytes() if path.exists() else None) == before
    await pilot.press("tab", "enter")
    assert app.stage == "saved", str(app.screen.query_one("#error", Static).content)
    await button(pilot, app, "close-saved")


def test_server_all_keyboard_defaults_and_confirm(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")

    async def run():
        app = ConfigWizard(d)
        async with app.run_test(size=(60, 24)) as p:
            await p.press("j", "j", "enter")
            assert app.stage == "server" and app.job is None
            await button(p, app, "next")
            assert app.stage == "storage"
            assert not app.screen.query_one("#storage_root_dir").display
            await button(p, app, "next")
            assert app.stage == "freshness"
            assert not app.screen.query_one("#freshness_warn_after").display
            await button(p, app, "next")
            await finish(p, app)

    asyncio.run(run())
    cfg = yaml.safe_load(d.path.read_bytes())
    assert cfg["server-settings"]["bind"] == {"host": "127.0.0.1", "port": 8000}
    assert cfg["storage-settings"]["enabled"] is False
    assert cfg["freshness-settings"]["enabled"] is False
    assert "publisher-settings" not in cfg


def test_publisher_manual_ids_advanced_and_custom_save(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            await p.press("j", "enter")
            app.screen.query_one("#destination", Input).value = (
                "https://receiver.example/base"
            )
            app.screen.query_one("#bearer", Input).value = "PUBLISH_KEY_UNSET"
            await button(p, app, "configure-watches")
            app.screen.query_one("#watch-path", Input).value = "never-opened.log"
            app.screen.query_one("#watch-id", Input).value = "logs:stable"
            await button(p, app, "add-watch")
            await button(p, app, "skip")
            assert app.stage == "publisher"
            app.screen.query_one("#manual-id", Input).value = "manual:dynamic"
            await button(p, app, "add-id")
            app.screen.query_one("#observe_view_interval_s", Input).value = "3"
            await button(p, app, "next")
            assert app.stage == "ready"
            await button(p, app, "advanced")
            assert app.stage == "advanced"
            await p.press("j", "enter")
            assert app.stage == "publish"
            app.screen.query_one("#stream_retry_max_delay_s", Input).value = "8"
            await button(p, app, "next")
            assert app.stage == "advanced"
            await p.press("escape")
            assert app.stage == "ready"
            app.save_path = str(tmp_path / "publisher-custom.yaml")
            await finish(p, app)

    asyncio.run(run())
    cfg = yaml.safe_load((tmp_path / "publisher-custom.yaml").read_bytes())
    assert "storage-settings" not in cfg and "server-settings" not in cfg
    assert cfg["publisher-settings"]["discovery"]["exact_selection"] == []
    assert cfg["publisher-settings"]["discovery"]["additional_ids"] == [
        "manual:dynamic"
    ]
    assert cfg["publisher-settings"]["watch"][0]["view_id"] == "logs:stable"
    assert cfg["publish-settings"]["observe"]["view_interval_s"] == 3
    assert cfg["stream-settings"]["retry_max_delay_s"] == 8


def test_combined_storage_and_freshness_overrides_persist_across_disable(tmp_path):
    (tmp_path / "app.py").write_text(
        'from plotsrv import view\n@view(label="Output", view_id="exact:one")\ndef f(): pass\n'
    )
    d = Draft.load(config=tmp_path / "plotsrv.yml", target=str(tmp_path))

    async def run():
        app = ConfigWizard(d)
        async with app.run_test(size=(70, 26)) as p:
            await p.press("enter")
            await button(p, app, "next")
            for _ in range(100):
                if app.stage == "selection":
                    break
                await p.pause(0.03)
            assert app.stage == "selection"
            await p.press("enter")
            assert app.stage == "storage"
            # Real keyboard select interaction, no mouse.
            await p.press("enter", "home", "enter")
            assert app.screen.query_one("#storage_root_dir").display
            app.screen.query_one("#storage_default_keep_last", Input).value = "9"
            await button(p, app, "overrides")
            await p.press("enter")
            assert app.screen.view_id == "exact:one"
            app.screen.query_one("#storage_default_keep_last", Input).value = "4"
            await button(p, app, "next")
            assert app.stage == "view_choices"
            await p.press("escape")
            assert app.stage == "storage"
            await button(p, app, "next")
            assert app.stage == "freshness"
            app.screen.query_one("#freshness_enabled", Select).value = "true"
            await p.pause()
            app.screen.query_one("#freshness_expected_every", Input).value = "1m"
            app.screen.query_one("#freshness_warn_after", Input).value = "2m"
            app.screen.query_one("#freshness_overdue_after", Input).value = "5m"
            await button(p, app, "next")
            assert app.stage == "ready"
            await p.press("escape")
            assert app.stage == "freshness"
            app.screen.query_one("#freshness_enabled", Select).value = "false"
            await p.pause()
            await button(p, app, "next")
            await finish(p, app)

    asyncio.run(run())
    cfg = yaml.safe_load(d.path.read_bytes())
    assert cfg["storage-settings"]["default_keep_last"] == 9
    assert cfg["storage-settings"]["views"]["exact:one"]["keep_last"] == 4
    assert cfg["freshness-settings"]["enabled"] is False
    assert cfg["freshness-settings"]["warn_after"] == "2m"
    assert cfg["publisher-settings"]["discovery"]["exact_selection"] == ["exact:one"]


def test_concurrent_edit_keeps_draft_and_explicit_rereview(tmp_path):
    path = tmp_path / "plotsrv.yml"
    path.write_text("# original\nstorage-settings: {enabled: false}\n")
    d = Draft.load(config=path)
    d.role = "server"

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            await p.press("enter")  # Server preselected by draft role.
            for stage in ("server", "storage", "freshness"):
                assert app.stage == stage
                await button(p, app, "next")
            await button(p, app, "review-path")
            await button(p, app, "next")
            path.write_text(
                "# external comment\nstorage-settings: {enabled: false}\nextra: keep\n"
            )
            await button(p, app, "save-reviewed")
            await p.press("tab", "enter")
            assert app.stage == "review"
            assert "changed" in str(app.screen.query_one("#error", Static).content)
            assert not list(tmp_path.glob("*.bak.*"))
            await button(p, app, "reload-review")
            await button(p, app, "save-reviewed")
            await p.press("tab", "enter")
            assert app.stage == "saved"

    asyncio.run(run())
    assert (
        "# external comment" in path.read_text() and "extra: keep" in path.read_text()
    )


def test_confirmation_cancel_then_abandon_preserves_bytes(tmp_path):
    path = tmp_path / "plotsrv.yml"
    raw = b"# unchanged\n"
    path.write_bytes(raw)
    d = Draft.load(config=path)
    d.role = "server"

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            await p.press("enter")
            for _ in range(3):
                await button(p, app, "next")
            await button(p, app, "review-path")
            await button(p, app, "next")
            await button(p, app, "save-reviewed")
            await p.press("escape")
            assert app.stage == "review"
            await p.press("ctrl+q", "tab", "enter")

    asyncio.run(run())
    assert path.read_bytes() == raw and list(tmp_path.iterdir()) == [path]


def test_local_routing_disclosure_watch_editor_and_dropdown_keys(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")
    d.add_watch("one.log", "logs:one", "tail")
    d.add_watch("two.log", "logs:two", "head")

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            await p.press("enter")
            assert app.focused.id == "target"
            assert not app.screen.query_one("#destination").display
            await button(p, app, "remote-routing")
            assert app.focused.id == "destination"
            assert app.screen.query_one("#destination").display
            choice = app.screen.query_one("#watch-choice", Select)
            choice.focus()
            await p.press("enter", "j", "enter")
            assert choice.value == 0
            assert app.screen.query_one("#watch-path", Input).value == "one.log"
            app.screen.query_one("#watch-label", Input).value = "Service log"
            app.screen.query_one("#watch-section", Input).value = "Operations"
            await button(p, app, "add-watch")
            assert len(d.watch_entries()) == 2
            assert d.watch_entries()[0]["label"] == "Service log"
            choice.value = 0
            await p.pause()
            await button(p, app, "remove-watch")
            assert [w.view_id for w in d.watches()] == ["logs:two"]
            assert not d.path.exists()

    asyncio.run(run())


def test_edit_then_disable_retains_dependent_values(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")
    d.role = "server"

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            await p.press("enter")
            await button(p, app, "next")
            app.screen.query_one("#storage_enabled", Select).value = "true"
            await p.pause()
            app.screen.query_one("#storage_default_keep_last", Input).value = "19"
            app.screen.query_one("#storage_enabled", Select).value = "false"
            await p.pause()
            await button(p, app, "next")
            app.screen.query_one("#freshness_enabled", Select).value = "true"
            await p.pause()
            app.screen.query_one("#freshness_warn_after", Input).value = "3m"
            app.screen.query_one("#freshness_enabled", Select).value = "false"
            await p.pause()
            await button(p, app, "next")
            await finish(p, app)

    asyncio.run(run())
    cfg = yaml.safe_load(d.path.read_bytes())
    assert cfg["storage-settings"]["default_keep_last"] == 19
    assert cfg["freshness-settings"]["warn_after"] == "3m"
    assert cfg["freshness-settings"]["enabled"] is False


def test_small_confirmation_scrolls_focused_action_into_view(tmp_path):
    from plotsrv.config_wizard.workflow import SaveConfirmation

    d = Draft.load(config=tmp_path / "plotsrv.yml")

    async def run():
        app = ConfigWizard(d)
        async with app.run_test(size=(40, 12)) as p:
            app.push_screen(SaveConfirmation())
            await p.pause()
            assert app.focused.id == "cancel-save"
            await p.press("tab")
            await p.pause()
            focused = app.focused
            assert focused.id == "confirm-save"
            assert app.screen.region.contains_region(focused.region)
            assert app.screen.query_one(
                "#dialog"
            ).scrollable_content_region.contains_region(focused.region)
            await p.press("escape")
            await p.press("enter")
            await p.resize_terminal(38, 10)
            await p.pause()
            assert app.focused.id == "target"
            assert app.screen.query_one("#content").scrollable_content_region.overlaps(
                app.focused.region
            )
            assert not d.path.exists()

    asyncio.run(run())


def test_combined_server_page_edits_server_ids_only(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")
    d.config = {
        "server-settings": {
            "admission": {"mode": "catalogue-locked", "allowed_ids": ["server-old"]}
        },
        "publisher-settings": {"discovery": {"additional_ids": ["publisher-old"]}},
    }
    d.discovery_skipped = True

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            app.go_workflow("server", advanced=True)
            await p.pause()
            assert "server-old" in str(
                app.screen.query_one("#manual-summary", Static).content
            )
            app.screen.query_one("#manual-id", Input).value = "server-new"
            await button(p, app, "add-id")
            assert d.configured_ids("server") == ["server-old", "server-new"]
            assert d.configured_ids("publisher") == ["publisher-old"]
            assert not d.path.exists()

    asyncio.run(run())


def test_watch_threshold_edit_keeps_disabled_choice(tmp_path):
    d = Draft.load(config=tmp_path / "plotsrv.yml")
    d.add_watch("service.log", "logs:service", "tail")

    async def run():
        app = ConfigWizard(d)
        async with app.run_test() as p:
            app.go_workflow("freshness", view_id="logs:service")
            await p.pause()
            assert app.screen.query_one("#freshness_enabled", Select).value == "false"
            app.screen.query_one("#freshness_warn_after", Input).value = "2m"
            assert app.screen.collect()
            assert d.section("freshness-settings")["views"]["logs:service"] == {
                "enabled": False,
                "warn_after": "2m",
            }

    asyncio.run(run())
