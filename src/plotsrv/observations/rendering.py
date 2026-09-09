"""Observation overview using plotsrv's normal table/plot explorer."""

from __future__ import annotations

from html import escape
import json

from ..renderers.base import RenderResult
from ..table_explorer_markup import render_table_explorer
from .history import compact
from .presentation import changes, project, shape
from .summary import validate_summary

MAX_BROWSER_BYTES = 192 * 1024


def _table(headers, rows):
    head = "".join(f"<th scope='col'>{escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<div class='ps-observation-scroll'><table class='ps-observation-facts'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_observation(
    summary,
    *,
    view_id,
    entries=(),
    pruned=False,
    snapshot=False,
    description=None,
    storage_message=None,
):
    try:
        return _render_observation(
            summary,
            view_id=view_id,
            entries=entries,
            pruned=pruned,
            snapshot=snapshot,
            description=description,
            storage_message=storage_message,
        )
    except Exception:
        # Wire validation bounds the tree, but unfamiliar nested evidence must
        # degrade without a raw-object fallback or a browser request failure.
        return RenderResult(
            kind="json",
            html='<p class="note">This observation format is unavailable. The published object has not been inspected again.</p>',
            meta={"observation": True},
        )


def _render_observation(
    summary, *, view_id, entries, pruned, snapshot, description, storage_message
):
    validate_summary(summary, view_id=view_id)
    data = project(summary, entries if not snapshot else ())
    previous = entries[-2] if len(entries) > 1 and not snapshot else None
    message, differences = changes(compact(summary), previous)
    inspected = sum(field["values_inspected"] for field in summary["fields"])
    uninspected = sum(field["not_inspected"] for field in summary["fields"])
    all_null = sum(
        bool(f.get("missingness", {}).get("denominator"))
        and f["missingness"]["missing"] == f["missingness"]["denominator"]
        for f in summary["fields"]
    )
    useful_probes = summary.get("exploration", {}).get("useful_values", 0)
    notes = []
    if all_null:
        notes.append(
            f"{all_null} {'field contains' if all_null == 1 else 'fields contain'} only missing values among those inspected."
        )
    if not data["distributions"]:
        notes.append(
            "No suitable observed distribution is available; supplied values and field coverage remain useful."
        )
    if useful_probes:
        notes.append(
            f"Exploratory probes found {useful_probes} useful values outside the base sample. They are excluded from its statistics."
        )
    if summary["reasons"]:
        notes.append(
            "Some analysis was limited. Capture details below explain why; selecting a few fields or a nested branch can help."
        )
    scope = (
        "Stored observation snapshot · fixed historical evidence"
        if snapshot
        else "Recent evidence in this server process · up to 16 observations per source"
    )
    history_note = (
        "This snapshot is fixed. Return to Latest explicitly to resume live updates. Its prior baseline is not loaded automatically."
        if snapshot
        else "Recent points are accepted observations, not every function call. Older entries may be evicted by per-source or shared memory limits."
    )
    if storage_message and not snapshot:
        history_note += " " + storage_message
    if pruned:
        history_note += (
            " Earlier evidence was evicted from this source's recent window."
        )
    diagnostics = summary.get("delivery", {})
    counts = [
        (name, diagnostics[name])
        for name in ("skipped", "dropped", "coalesced", "failed")
        if type(diagnostics.get(name)) is int and diagnostics[name] > 0
    ]
    if counts:
        history_note += (
            " Publisher-process diagnostics (all its views, best effort): "
            + ", ".join(f"{count} {name}" for name, count in counts)
            + ". Gaps are not filled or attributed to this source."
        )
    if previous and summary.get("provenance", {}).get(
        "publisher_session"
    ) == previous.get("provenance", {}).get("publisher_session"):
        if any(
            type(diagnostics.get(k)) is int
            and type(previous.get("delivery", {}).get(k)) is int
            and diagnostics[k] < previous["delivery"][k]
            for k in ("skipped", "dropped", "coalesced", "failed")
        ):
            history_note += (
                " Publisher diagnostics reset; count differences are unavailable."
            )
    technical = {
        key: summary[key]
        for key in (
            "source_type",
            "captured_at_unix_s",
            "provenance",
            "sampling",
            "coverage",
            "reasons",
        )
    }
    encoded = json.dumps(
        data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    if len(encoded.encode()) > MAX_BROWSER_BYTES:
        # Bound the browser projection independently of the publisher's wire cap.
        data["rows"] = [row for row in data["rows"] if row["surface"] == "Fields"]
        data["recipes"] = data["recipes"][:1]
        data["examples"] = []
        notes.append(
            "Additional presentation rows were omitted to keep this browser view bounded."
        )
        encoded = json.dumps(
            data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
    if len(encoded.encode()) > MAX_BROWSER_BYTES:
        data["rows"] = []
        encoded = json.dumps(
            data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
    if len(encoded.encode()) > MAX_BROWSER_BYTES:
        raise ValueError("observation presentation budget")
    examples_html = ""
    if data["examples"]:
        examples_html = (
            '<details class="ps-observation-section"><summary>Examples / sample · explicitly enabled, up to 16 values</summary>'
            + _table(
                ["Field", "Position", "Captured value", "Evidence"], data["examples"]
            )
            + "</details>"
        )
    elif summary["examples_enabled"]:
        notes.append(
            "Examples were allowed, but no displayable examples were retained."
        )
    details = json.dumps(technical, ensure_ascii=False, allow_nan=False, indent=2)
    changes_html = (
        _table(["Measure", "Prior", "Current", "Scope"], differences)
        if differences
        else ""
    )
    description_html = (
        f'<p class="note">{escape(description)}</p>' if description else ""
    )
    explorer = render_table_explorer(
        grid_html='<div class="table-grid ps-tablegrid ps-table--rich" data-observation-grid="1"></div>',
        search_placeholder="Search captured evidence…",
    )
    overview = f"""<section class="ps-observation-overview" aria-labelledby="observation-title">
      <h2 id="observation-title">Observation overview</h2>{description_html}
      <p class="note">{escape(scope)}</p>
      <dl class="ps-observation-metadata"><div><dt>Source</dt><dd>{escape(summary['source_type'])}</dd></div>
      <div><dt>Known shape / length</dt><dd>{escape(shape(summary))}</dd></div>
      <div><dt>Captured fields</dt><dd>{len(summary['fields'])}</dd></div>
      <div><dt>Values inspected</dt><dd>{inspected} · {uninspected} not inspected</dd></div></dl>
      <p class="note">Sampling: {escape(str(summary['sampling']['method']).replace('_', ' '))}. Statistics describe inspected evidence; shape describes cheap source metadata. Full positional coverage is not an atomic snapshot.</p>
      {''.join('<p class="note">' + escape(note) + '</p>' for note in notes)}
    </section>"""
    html = f"""<div data-plotsrv-observation="1" class="ps-observation">
      {overview}
      <section class="ps-observation-section" aria-labelledby="observation-changes-title"><h3 id="observation-changes-title">Changes</h3><p class="note">{escape(message)}</p>{changes_html}<p class="note">{escape(history_note)}</p></section>
      <section aria-label="Fields and distributions">{explorer}</section>
      {examples_html}
      <details class="ps-observation-section"><summary>Capture details and provenance</summary><pre class="plotsrv-pre plotsrv-pre--wrap">{escape(details)}</pre></details>
      <div hidden data-observation-data="1">{escape(encoded)}</div>
    </div>"""
    return RenderResult(
        kind="json",
        html=html,
        meta={
            "observation": True,
            "observation_version": 1,
            "history_scope": "snapshot" if snapshot else "process",
            "recent_count": len(entries) if not snapshot else 0,
        },
    )
