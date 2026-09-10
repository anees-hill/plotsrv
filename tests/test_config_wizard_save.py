from __future__ import annotations
import asyncio
import os
from pathlib import Path
import stat
import pytest
import yaml

from plotsrv import settings, config
from plotsrv.config_wizard.draft import Draft, FIELDS, _load_bounded
from plotsrv.config_wizard import schema
from plotsrv.config_wizard.saving import (
    DELETE,
    SaveError,
    narrow_yaml,
    prepare,
    read_snapshot,
    save,
)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_NAME", raising=False)
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    import urllib.request, requests

    def network(*a, **kw):
        pytest.fail("Wizard contacted a service")

    monkeypatch.setattr(urllib.request, "urlopen", network)
    monkeypatch.setattr(requests.Session, "request", network)


def load(tmp_path, raw=None, role="server", name=None):
    path = tmp_path / "plotsrv.yml"
    if raw is not None:
        path.write_bytes(raw)
    d = Draft.load(config=path, name=name)
    d.role = role
    return d


def test_narrow_comments_instances_and_production_reload(tmp_path):
    raw = b'# keep header\nstorage-settings:\n  default:\n    enabled: false # retain inline\n    root_dir: "my data"\n  instances:\n    mine:\n      default_keep_last: 3 # mine\n    someone_else: {enabled: true, root_dir: other} # untouched\ncustom: |\n  unrelated secret material\n  stays byte-identical\n'
    d = load(tmp_path, raw, name="mine")
    d.set_value(FIELDS["storage_enabled"], "true")
    d.set_value(FIELDS["storage_default_keep_last"], "8")
    d.set_value(FIELDS["freshness_enabled"], "true")
    r = prepare(d, str(d.path))
    assert d.path.read_bytes() == raw
    assert b"someone_else: {enabled: true, root_dir: other} # untouched" in r.proposed
    assert b'root_dir: "my data"' in r.proposed
    assert (
        b"custom: |\n  unrelated secret material\n  stays byte-identical\n"
        in r.proposed
    )
    assert "unrelated secret" not in r.text
    backup = save(r)
    assert backup.read_bytes() == raw
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    settings.set_runtime_context(config_path=d.path, name="mine")
    assert config.get_storage_enabled() is True
    assert config.get_storage_default_keep_last() == 8
    assert config.get_freshness_enabled() is True
    assert (
        settings.effective_section(
            settings.load_config(), "storage-settings", name="someone_else"
        )["root_dir"]
        == "other"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"# comment only\n",
        b"{} # empty\n",
        b"storage-settings: {enabled: false} # flow\n",
        b"storage-settings:\r\n  enabled: false # old\r\nunrelated: yes\r\n",
    ],
)
def test_narrow_layouts(tmp_path, raw):
    d = load(tmp_path, raw)
    d.set_value(FIELDS["storage_enabled"], "true")
    d.set_value(FIELDS["freshness_warn_after"], "2m")
    r = prepare(d, str(d.path))
    assert _load_bounded(r.proposed)["storage-settings"]["enabled"] is True
    assert b"#" in r.proposed
    save(r)


def test_new_custom_config_and_no_clobber(tmp_path):
    d = load(tmp_path)
    d.set_value(FIELDS["storage_enabled"], "true")
    custom = tmp_path / "chosen.yaml"
    r = prepare(d, str(custom))
    assert not d.path.exists() and not custom.exists()
    assert "--config" in r.text and "chosen.yaml" in r.text
    assert save(r) is None
    assert yaml.safe_load(custom.read_bytes())["storage-settings"]["enabled"] is True
    assert stat.S_IMODE(custom.stat().st_mode) == 0o600
    with pytest.raises(SaveError, match="changed"):
        save(r)


def test_concurrent_edit_before_review_and_before_save(tmp_path):
    d = load(tmp_path, b"# original\n")
    d.set_value(FIELDS["storage_enabled"], "true")
    r = prepare(d, str(d.path))
    d.path.write_text("# external\n")
    with pytest.raises(SaveError, match="changed"):
        save(r)
    with pytest.raises(SaveError, match="changed"):
        prepare(d, str(d.path))
    assert d.path.read_text() == "# external\n"
    assert not list(tmp_path.glob("*.bak.*"))
    assert d.edits


def test_mtime_change_is_not_hidden_by_equal_content(tmp_path):
    d = load(tmp_path, b"# original\n")
    r = prepare(d, str(d.path))
    current = d.path.stat()
    os.utime(d.path, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000))
    with pytest.raises(SaveError, match="changed"):
        save(r)


@pytest.mark.parametrize("operation", ["mkstemp", "replace", "fsync", "link"])
def test_failed_write_preserves_target_and_draft(tmp_path, monkeypatch, operation):
    from plotsrv.config_wizard import saving

    original = None if operation == "link" else b"# original\n"
    d = load(tmp_path, original)
    d.set_value(FIELDS["storage_enabled"], "true")
    r = prepare(d, str(d.path))

    def fail(*a, **kw):
        raise PermissionError("SECRET must not appear")

    if operation == "mkstemp":
        monkeypatch.setattr(saving.tempfile, "mkstemp", fail)
    else:
        monkeypatch.setattr(saving.os, operation, fail)
    with pytest.raises(SaveError) as error:
        save(r)
    assert "SECRET" not in str(error.value)
    assert (d.path.read_bytes() if d.path.exists() else None) == original
    assert not list(tmp_path.glob("*.tmp"))
    assert d.edits


def test_unique_backups_never_overwrite(tmp_path):
    d = load(tmp_path, b"storage-settings: {enabled: false}\n")
    d.set_value(FIELDS["storage_enabled"], "true")
    first = save(prepare(d, str(d.path)))
    old = first.read_bytes()
    d = Draft.load(config=d.path)
    d.role = "server"
    d.set_value(FIELDS["storage_enabled"], "false")
    second = save(prepare(d, str(d.path)))
    assert first != second and first.read_bytes() == old
    assert yaml.safe_load(second.read_bytes())["storage-settings"]["enabled"] is True


def test_ambiguous_yaml_and_commented_list_refuse(tmp_path):
    with pytest.raises(ValueError):
        narrow_yaml(b"x: 1\nx: 2\n", {("x",): 3})
    with pytest.raises(SaveError, match="comments"):
        narrow_yaml(
            b"x:\n  - first # do not discard\n", {("x",): {"replacement": True}}
        )
    assert (
        narrow_yaml(b"x:\n  - first # keep\n", {("x",): ["first"]})
        == b"x:\n  - first # keep\n"
    )


def test_per_view_inheritance_reset_and_disabled_values(tmp_path):
    raw = b'storage-settings:\n  enabled: true\n  default_keep_last: 9\n  views:\n    "exact:id":\n      keep_last: 4 # override\n      unrelated: preserve\nfreshness-settings:\n  enabled: false\n  warn_after: 2m\n'
    d = load(tmp_path, raw)
    fields = schema.fields_for("storage", d, "exact:id")
    spec = next(s for s in fields if s.path[-1] == "keep_last")
    assert d.value(spec) == 4 and spec.default == 9
    d.edits[spec.path] = DELETE
    d.set_value(FIELDS["storage_enabled"], "false")
    r = prepare(d, str(d.path))
    save(r)
    settings.set_runtime_context(config_path=d.path)
    assert config.get_storage_keep_last("exact:id") == 9
    assert config.get_freshness_warn_after_s() == 120
    assert config.get_storage_enabled() is False
    assert b"unrelated: preserve" in d.path.read_bytes()


def test_actual_defaults_and_observe_safety_caps(tmp_path):
    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://receiver.example/prefix")
    assert (
        d.value(FIELDS["storage_default_keep_last"])
        == config._DEFAULTS["storage-settings"]["default_keep_last"]
    )
    assert d.value(FIELDS["freshness_warn_after"]) is None
    d.set_value(FIELDS["observe_max_rows"], "10000")
    with pytest.raises(SaveError, match="max_rows"):
        prepare(d, str(d.path))
    assert not d.path.exists()


def test_environment_references_not_resolved_or_leaked(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_NAME", "DO_NOT_SHOW_SECRET")
    raw = b"server-settings:\n  ingestion:\n    bearer_token_env: SECRET_NAME\nwebhook-settings:\n  destinations:\n    notify:\n      url: https://hooks.example/private-secret-path\n      headers_env: {Authorization: UNSET_ON_THIS_MACHINE}\n"
    d = load(tmp_path, raw)
    d.set_value(FIELDS["bind_host"], "0.0.0.0")
    r = prepare(d, str(d.path))
    assert "DO_NOT_SHOW_SECRET" not in r.text and "private-secret-path" not in r.text
    assert "SECRET_NAME" in r.text
    assert b"UNSET_ON_THIS_MACHINE" in r.proposed
    save(r)


def test_exposure_and_freshness_validation(tmp_path):
    d = load(tmp_path)
    d.set_value(FIELDS["bind_host"], "0.0.0.0")
    with pytest.raises(SaveError, match="exposure"):
        prepare(d, str(d.path))
    d.set_value(FIELDS["allow_remote"], "true")
    d.set_value(FIELDS["freshness_warn_after"], "10m")
    d.set_value(FIELDS["freshness_overdue_after"], "1m")
    with pytest.raises(SaveError, match="precede"):
        prepare(d, str(d.path))


def test_exact_empty_selection_and_manual_ids_reload(tmp_path):
    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://server/")
    d.discovery_skipped = True
    d.add_id("manual:stable")
    save(prepare(d, str(d.path)))
    settings.set_runtime_context(config_path=d.path)
    from plotsrv.source_setup import resolve_source_setup, build_manifest
    from plotsrv.discovery import DiscoveredView

    setup = resolve_source_setup()
    assert setup.exact_selection == () and setup.additional_ids == ("manual:stable",)
    result = build_manifest(
        [DiscoveredView("unknown", "not-selected", None)],
        exact_selection=setup.exact_selection,
        added_ids=setup.additional_ids,
    )
    assert [v["view_id"] for v in result["views"]] == ["manual:stable"]


def test_append_watch_preserves_existing_row_comments(tmp_path):
    raw = b"publisher-settings:\n  destination: {url: https://server/}\n  watch:\n    - path: old.log # retain source comment\n      view_id: logs:old\nother: untouched # next section\n"
    d = load(tmp_path, raw, role="publisher")
    d.add_watch("new.log", "logs:new", None)
    r = prepare(d, str(d.path))
    assert b"path: old.log # retain source comment" in r.proposed
    assert b"other: untouched # next section" in r.proposed
    assert len(yaml.safe_load(r.proposed)["publisher-settings"]["watch"]) == 2


def test_new_folder_preserves_explicit_source_base(tmp_path):
    folder = tmp_path / "destination"
    folder.mkdir()
    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://server/")
    d.add_watch("my.log", "logical:id", None)
    r = prepare(d, str(folder / "new.yml"))
    cfg = yaml.safe_load(r.proposed)
    assert cfg["publisher-settings"]["watch"][0]["path"] == str(tmp_path / "my.log")


def test_legacy_off_and_nullable_local_destination(tmp_path):
    d = load(
        tmp_path,
        b"publisher-settings:\n  destination: null\nstorage-settings:\n  default_min_store_interval: off\nfreshness-settings:\n  warn_after: off\n",
        role="combined",
    )
    assert d.value(FIELDS["destination"]) is None
    assert d.value(FIELDS["freshness_warn_after"]) is None
    assert d.value(FIELDS["storage_default_min_store_interval"]) is None
    prepare(d, str(d.path))
    d.set_value(FIELDS["destination"], "https://remote/")
    assert b"https://remote/" in prepare(d, str(d.path)).proposed


def test_reset_watch_freshness_removes_opt_in_entry(tmp_path):
    raw = b"freshness-settings:\n  enabled: true\n  views:\n    logs:watched: {warn_after: 2m}\n"
    d = load(tmp_path, raw)
    d.reset_overrides(schema.fields_for("freshness", d, "logs:watched"), "logs:watched")
    # Flow mapping entry removal is performed at its block parent, preserving
    # unrelated sections; it must not leave a new empty opt-in object.
    save(prepare(d, str(d.path)))
    settings.set_runtime_context(config_path=d.path)
    assert not config.has_freshness_view_config("logs:watched")


def test_deleting_absent_override_never_creates_a_view():
    assert (
        narrow_yaml(
            b"freshness-settings: {enabled: true}\n",
            {("freshness-settings", "views", "not-present", "warn_after"): DELETE},
        )
        == b"freshness-settings: {enabled: true}\n"
    )


def test_run_honours_saved_bind_and_empty_exact_selection(tmp_path, monkeypatch):
    from plotsrv import cli

    d = load(tmp_path, role="combined")
    d.discovery_skipped = True
    d.set_value(FIELDS["bind_port"], "8227")
    d.add_id("manual:placeholder")
    save(prepare(d, str(d.path)))
    captured = {}
    monkeypatch.setattr(
        cli, "_run_passive_server_forever", lambda *a, **kw: captured.update(kw) or 0
    )
    assert cli.main(["run", "--config", str(d.path)]) == 0
    assert captured["port"] == 8227
    assert captured["exact_selection"] == ()
    assert captured["additional_ids"] == ("manual:placeholder",)
    assert cli.main(["run", "--config", str(d.path), "--port", "8228"]) == 0
    assert captured["port"] == 8228


def test_passive_empty_exact_selection_never_scans(tmp_path, monkeypatch):
    from plotsrv import cli

    registrations = []
    monkeypatch.setattr(
        cli,
        "discover_views",
        lambda *a, **kw: pytest.fail("Empty exact selection must skip AST"),
    )
    monkeypatch.setattr(
        cli.store, "register_view", lambda **kw: registrations.append(kw)
    )
    monkeypatch.setattr(cli.store, "set_active_view", lambda *a: None)
    cli._passive_register_views(
        "/missing/source",
        excludes=set(),
        includes=set(),
        exact_selection=(),
        additional_ids=("manual:id",),
    )
    assert registrations[0]["view_id"] == "manual:id"


def test_exact_selection_is_not_a_label_or_section_filter():
    from plotsrv.source_setup import select_views
    from plotsrv.discovery import DiscoveredView

    views = [
        DiscoveredView("unknown", "label", "section", "exact"),
        DiscoveredView("unknown", "exact", "section", "other"),
    ]
    assert len(select_views(views, selection=[])) == 2
    assert [v.view_id for v in select_views(views, exact_selection=["exact"])] == [
        "exact"
    ]
    assert select_views(views, exact_selection=[]) == []


def test_publisher_uses_configured_manual_ids_without_discovery(tmp_path, monkeypatch):
    from plotsrv import cli, publisher_agent

    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://receiver/")
    d.discovery_skipped = True
    d.add_id("dynamic:one")
    save(prepare(d, str(d.path)))
    sent = []
    monkeypatch.setattr(
        publisher_agent,
        "request_json",
        lambda target, route, payload, **kw: sent.append((route, payload))
        or {"ok": True},
    )
    assert cli.main(["publish", "--config", str(d.path), "--quiet"]) == 0
    assert sent[0][0] == "/catalogue/register"
    assert [v["view_id"] for v in sent[0][1]["views"]] == ["dynamic:one"]


def test_populate_respects_exact_empty_selection_and_manual_ids(tmp_path, monkeypatch):
    from plotsrv import config_writer

    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://receiver/")
    d.discovery_skipped = True
    d.add_id("manual:policy")
    save(prepare(d, str(d.path)))
    monkeypatch.setattr(
        config_writer,
        "discover_views",
        lambda *a, **kw: pytest.fail("No scan for exact empty selection"),
    )
    config_writer.populate_freshness(path=d.path, target=tmp_path)
    assert set(yaml.safe_load(d.path.read_bytes())["freshness-settings"]["views"]) == {
        "manual:policy"
    }


def test_skip_missing_cli_target_and_preserve_callable_suffix(tmp_path):
    d = load(tmp_path, role="publisher")
    d.set_value(FIELDS["destination"], "https://receiver/")
    d.cli_target = "missing/path.py"
    d.discovery_skipped = True
    prepare(d, str(d.path))
    source = tmp_path / "app.py"
    source.write_text("def operation(): pass\n")
    d.cli_target = str(source) + ":operation"
    d.discovery_skipped = False
    proposed = yaml.safe_load(prepare(d, str(d.path)).proposed)
    assert proposed["publisher-settings"]["discovery"]["target"].endswith(
        "app.py:operation"
    )


@pytest.mark.parametrize(
    "thresholds",
    [
        "  expected_every: 5m\n  overdue_after: 2m\n",
        "  warn_after: 5m\n  overdue_after: null\n  error_after: 2m\n",
        "  warn_after: 5m\n  overdue_after: 10m\n  views:\n    output:\n      error_after: 2m\n",
    ],
)
def test_freshness_validates_effective_and_legacy_thresholds(tmp_path, thresholds):
    d = load(tmp_path, ("freshness-settings:\n" + thresholds).encode())
    with pytest.raises(SaveError, match="must not precede"):
        prepare(d, str(d.path))


def test_explicit_null_view_overdue_uses_runtime_derived_threshold(tmp_path):
    d = load(
        tmp_path,
        b"freshness-settings:\n  warn_after: 1m\n  overdue_after: 2m\n  views:\n    output:\n      warn_after: 5m\n      overdue_after: null\n",
    )
    prepare(d, str(d.path))
