from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml

from plotsrv import settings
from plotsrv.cli_parser import build_parser
from plotsrv.config_wizard.draft import Draft
from plotsrv.config_wizard.flow import _current_role, run
from plotsrv.config_wizard.inputs import Prompts, format_size, parse_duration, parse_size


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app.py").write_text(
        "from plotsrv import view\n"
        "raise RuntimeError('AST discovery must not execute code')\n"
        "@view(label='Alpha', view_id='exact:alpha')\ndef first(): pass\n"
        "@view(label='Beta', view_id='exact:beta')\ndef second(): pass\n"
    )
    return tmp_path


def wizard(path: Path, *, target: str | None = None, answers=None, existing=None):
    if existing is not None:
        path.write_text(existing)
    output = io.StringIO()
    supplied = {key: list(values) for key, values in (answers or {}).items()}

    def read():
        question = output.getvalue().splitlines()[-1]
        for prefix, values in supplied.items():
            if question.startswith(prefix) and values:
                return values.pop(0)
        return ""

    draft = Draft.load(config=path, target=target)
    result = run(draft, Prompts(reader=read, output=output))
    return result, output.getvalue(), draft


def test_first_run_defaults_create_minimal_combined_config(project):
    path = project / "plotsrv.yml"
    result, output, _ = wizard(
        path, target=str(project), answers={"Write this configuration?": ["y"]},
    )
    data = yaml.safe_load(path.read_text())
    assert result == path
    assert data["server-settings"]["bind"] == {"host": "127.0.0.1", "port": 8000}
    assert data["storage-settings"]["enabled"] is True
    assert data["freshness-settings"]["expected_every"] == "60s"
    assert data["publisher-settings"]["discovery"]["target"] == str(project)
    assert "Found 2 plotsrv views" in output
    assert "Tip: enter ?" in output
    assert "@view" not in path.read_text()  # Discovery did not copy or execute source.


@pytest.mark.parametrize("role", ["publisher", "server"])
def test_role_gates_questions_and_sections(project, role):
    path = project / "plotsrv.yml"
    answers = {
        "How will this installation": [role],
        "Destination URL": ["https://example.org/base"] if role == "publisher" else [],
        "Write this configuration?": ["y"],
    }
    _, output, _ = wizard(path, target=str(project), answers=answers)
    data = yaml.safe_load(path.read_text())
    assert "Found 2 plotsrv views" in output
    if role == "publisher":
        assert "Storage\n" not in output
        assert "server-settings" not in data
        assert data["publisher-settings"]["destination"]["url"] == "https://example.org/base/"
    else:
        assert "Destination URL" not in output
        assert "publisher-settings" not in data
        assert data["server-settings"]["bind"]["port"] == 8000


def test_help_invalid_input_and_view_selection(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "Hide any discovered views?": ["y"],
        "Which views should be hidden?": ["7", "2"],
        "Enable storage?": ["?", "maybe", "n"],
        "Enable freshness monitoring?": ["n"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["publisher-settings"]["discovery"]["exact_selection"] == ["exact:alpha"]
    assert data.get("storage-settings", {}).get("enabled", False) is False
    assert "Storage saves latest values" in output
    assert "Choose numbers from 1 to 2" in output
    assert "Enter y or n" in output


def test_storage_freshness_and_per_view_overrides(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "Customise storage?": ["y"],
        "Maximum snapshot size": ["500 KB"],
        "Snapshots retained per view": ["8"],
        "Customise individual views?": ["y", "y"],
        "Choose views to customise": ["1", "2"],
        "Snapshots retained per view [": ["4", ""],
        "Customise another view?": ["n", "n"],
        "Configure advanced storage settings?": ["n"],
        "Customise freshness?": ["y"],
        "Expected update interval": ["3 am", "4h"],
        "Warning threshold": ["5h"],
        "Overdue threshold": ["2d"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["storage-settings"]["max_snapshot_size_mb"] == pytest.approx(500 / 1024)
    assert data["storage-settings"]["views"]["exact:alpha"]["keep_last"] == 4
    assert data["freshness-settings"]["expected_every"] == "4h"
    assert data["freshness-settings"]["warn_after"] == "5h"
    assert data["freshness-settings"]["overdue_after"] == "2d"
    assert "Enter a duration" in output
    assert "Size example" in output


def test_human_friendly_size_and_duration_inputs():
    assert parse_size("500 KB") == 500 * 1024
    assert parse_size("1.5 GB") == int(1.5 * 1024**3)
    assert parse_size("1048576") == 1048576
    assert parse_size("500 KB", megabytes=True) == 500 / 1024
    assert format_size(5242880) == "5 MiB"
    assert format_size(1000) == "1,000 B"
    assert format_size(5300001) == "5.05 MiB (5,300,001 B)"
    assert parse_duration(" 30 m ") == "30m"
    assert parse_duration("2D") == "2d"
    for value in ("3am", "0m", "bogus"):
        with pytest.raises(ValueError):
            parse_duration(value)
    with pytest.raises(ValueError):
        parse_size("1.5 bytes")


def test_watched_file_addition_customisation_and_storage_context(project):
    path = project / "plotsrv.yml"
    watched = project / "events.jsonl"
    watched.write_text("{}\n")
    _, output, _ = wizard(path, target=str(project), answers={
        "Add a watched file?": ["y"],
        "File path": ["events.jsonl"],
        "Customise this watched file?": ["y"],
        "Read mode": ["tail"],
        "Representation": ["file"],
        "Customise storage for this watched file?": ["y"],
        "Store watched-file snapshots": ["n", "yes"],
        "Change another watched file?": ["n"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    row = data["publisher-settings"]["watch"][0]
    assert row["path"] == "events.jsonl"
    assert row["label"] == "events"
    assert row["read_mode"] == "tail"
    assert row["materialization"] == "file"
    assert "view_id" not in row
    assert data["storage-settings"]["views"]["watch:events"]["watch_enabled"] is True
    assert "Store watched-file snapshots" in output
    assert "publisher-settings.watch.watch:events.path" in output


def test_existing_config_preserved_and_no_change_rerun(project):
    path = project / "plotsrv.yml"
    raw = "# human comment\nserver-settings: {bind: {host: 127.0.0.1, port: 8000}}\nunknown: {keep: true}\n"
    _, output, _ = wizard(path, target=str(project), existing=raw)
    assert path.read_text() == raw
    assert "No changes" in output
    assert "Write this configuration?" not in output
    _, _, _ = wizard(path, target=str(project), answers={
        "Change storage settings?": ["y"],
        "Enable storage?": ["y"],
        "Write this configuration?": ["y"],
    })
    assert "# human comment" in path.read_text()
    assert "unknown: {keep: true}" in path.read_text()
    assert yaml.safe_load(path.read_text())["storage-settings"]["enabled"] is True
    assert list(project.glob("plotsrv.yml.bak.*"))


def test_starter_sections_do_not_imply_server_only(project):
    path = project / "plotsrv.yml"
    path.write_text("storage-settings: {enabled: false}\nfreshness-settings: {enabled: false}\n")
    assert _current_role(Draft.load(config=path)) == "combined"


def test_cancel_and_decline_review_leave_existing_bytes(project):
    path = project / "plotsrv.yml"
    raw = "# unchanged\nserver-settings: {bind: {port: 8000}}\n"
    _, output, _ = wizard(path, target=str(project), existing=raw, answers={
        "Change storage settings?": ["y"], "Enable storage?": ["y"],
    })
    assert "Not saved" in output
    assert path.read_text() == raw

    output = io.StringIO()
    def interrupt():
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(Draft.load(config=path, target=str(project)), Prompts(reader=interrupt, output=output))
    assert path.read_text() == raw


def test_no_ansi_in_plain_terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    output = Terminal()
    prompts = Prompts(reader=lambda: "", output=output)
    prompts.section("Storage")
    assert "\x1b[" not in output.getvalue()


def test_limits_invalid_size_reprompts_and_shows_binary_units(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "Customise safety limits?": ["y"],
        "Max plot bytes": ["lots", "10 MB"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["limits"]["published_objects"]["max_plot_bytes"] == 10 * 1024**2
    assert "Enter a size such as" in output


def test_freshness_threshold_order_reprompts_in_section(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "Customise freshness?": ["y"],
        "Warning threshold": ["5h"],
        "Overdue threshold": ["1h", "6h"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["freshness-settings"]["overdue_after"] == "6h"
    assert "Overdue must be later" in output


def test_duplicate_watched_path_offers_edit_and_keeps_single_entry(project):
    path = project / "plotsrv.yml"
    (project / "events.log").write_text("test\n")
    _, output, _ = wizard(path, target=str(project), answers={
        "Add a watched file?": ["y"],
        "File path": ["events.log", "./events.log"],
        "Change another watched file?": ["y", "n"],
        "Choose an action": ["add"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert len(data["publisher-settings"]["watch"]) == 1
    assert "Already watched as events" in output
    assert "Edit that entry instead?" in output


def test_storage_disabled_omits_watch_snapshot_questions(project):
    path = project / "plotsrv.yml"
    (project / "events.log").write_text("test\n")
    _, output, _ = wizard(path, target=str(project), answers={
        "Enable storage?": ["n"],
        "Add a watched file?": ["y"],
        "File path": ["events.log"],
        "Write this configuration?": ["y"],
    })
    assert "Store watched-file snapshots" not in output
    assert "Customise storage for this watched file?" not in output


def test_publisher_destination_validates_at_prompt(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "How will this installation": ["publisher"],
        "Destination URL": ["off", "http://example.test/base"],
        "Write this configuration?": ["y"],
    })
    assert "http://example.test/base/" in path.read_text()
    assert "destination must be an HTTP(S) base URL" in output


def test_explicit_per_view_choice_is_override_even_if_equal_to_inherited(project):
    path = project / "plotsrv.yml"
    _, _, _ = wizard(path, target=str(project), answers={
        "Customise storage?": ["y"],
        "Customise individual views?": ["y"],
        "Choose views to customise": ["1"],
        "Keep snapshots on disk": ["yes"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["storage-settings"]["views"]["exact:alpha"]["enabled"] is True


def test_per_view_limit_is_reviewed_and_saved(project):
    path = project / "plotsrv.yml"
    _, output, _ = wizard(path, target=str(project), answers={
        "Customise safety limits?": ["y"],
        "Customise truncation for individual views?": ["y"],
        "Choose views": ["1"],
        "Text character limit": ["500"],
        "Write this configuration?": ["y"],
    })
    data = yaml.safe_load(path.read_text())
    assert data["limits"]["views"]["exact:alpha"]["truncate_after"]["text"] == 500
    assert "limits.views.exact:alpha.truncate_after.text" in output


def test_launch_handles_interrupt_without_writing(project, monkeypatch, capsys):
    from plotsrv.config_wizard import launch

    path = project / "plotsrv.yml"
    args = build_parser().parse_args(["config", "init", str(project), "--config", str(path)])
    monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(KeyboardInterrupt))
    assert launch(args) == 130
    assert not path.exists()
    assert "Configuration cancelled" in capsys.readouterr().err


def test_config_init_parser():
    args = build_parser().parse_args(["config", "init", "./src", "--name", "etl"])
    assert args.target == "./src" and args.name == "etl"
