"""Observation overview using plotsrv's normal table/plot explorer."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import re

from ..renderers.base import RenderResult
from ..table_explorer_markup import render_table_explorer
from .history import compact
from .presentation import changes, field_name, project, typed
from .summary import validate_summary

MAX_BROWSER_BYTES = 192 * 1024
EVIDENCE_LABELS = {
    "base_sample": "Sampled values",
    "supplied_value": "Supplied value",
    "complete_small_inspection": "Complete small inspection",
    "captured_structure": "Captured structure",
}


def _count(value):
    return f"{value:,}" if type(value) is int else str(value)


def _dimensions(summary):
    dimensions = summary.get("metadata", {}).get("shape")
    rows = dimensions[0] if isinstance(dimensions, list) and dimensions else None
    fields = (
        dimensions[1]
        if isinstance(dimensions, list)
        and len(dimensions) > 1
        and type(dimensions[1]) is int
        else len(summary["fields"])
    )
    return rows, fields


def _observation_mode(summary):
    method = summary.get("sampling", {}).get("method")
    return {
        "deterministic_distributed_positions": "Sampled observation",
        "bounded_insertion_order_fields": "Bounded field observation",
        "single_value_or_unsupported": "Single-value observation",
    }.get(method, "Bounded observation")


def _captured_time(summary):
    try:
        value = datetime.fromtimestamp(
            summary["captured_at_unix_s"], timezone.utc
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return "time unavailable"
    return value.strftime("%d %b %Y, %H:%M:%S UTC").lstrip("0")


def _identifier_like(name):
    return bool(
        re.search(
            r"(?:^|[\s_.-])(id|uuid|guid|key|code)(?:$|[\s_.-])",
            name,
            re.IGNORECASE,
        )
    )


def _field_rows(summary, differences):
    changed = {
        measure.removesuffix(" · observed mean").removesuffix(
            " · observed missing"
        )
        for measure, *_ in differences
        if measure not in ("Known shape/length", "Captured schema")
    }
    rows = []
    metadata = summary["metadata"]
    for field in summary["fields"]:
        name = field_name(field, metadata)
        missing = field.get("missingness", {})
        denominator = missing.get("denominator")
        missing_count = missing.get("missing")
        if type(missing_count) is int and type(denominator) is int:
            missing_label = (
                _count(missing_count)
                if not missing_count
                else f"{_count(missing_count)} of {_count(denominator)}"
            )
        else:
            missing_label = "Not inspected"

        numeric = field.get("numeric", {})
        if "min" in numeric and "max" in numeric:
            observed_range = f"{typed(numeric['min'])} – {typed(numeric['max'])}"
        else:
            observed_range = "—"

        typical = "—"
        if field.get("scope") == "supplied_value" and "value" in field:
            typical = typed(field["value"])
        elif not _identifier_like(name):
            median = numeric.get("quantiles", {}).get("p50")
            categories = field.get("categories", {}).get("top", [])
            if median is not None:
                typical = typed(median)
            elif categories:
                typical = typed(categories[0]["value"])

        rows.append(
            {
                "name": name,
                "missing": missing_label,
                "range": observed_range,
                "typical": typical,
                "changed": name in changed,
                "inspected": field["values_inspected"],
                "evidence": EVIDENCE_LABELS.get(
                    field.get("scope"), "Observed evidence"
                ),
            }
        )
    return rows


def _findings(summary, differences, field_rows):
    findings = []
    for measure, before, after, basis in differences:
        field = None
        if measure == "Known shape/length":
            title, detail = "Dataset size changed", f"{before} → {after}"
        elif measure == "Captured schema":
            title, detail = "Field structure changed", after
        elif measure.endswith(" · observed missing"):
            field = measure.removesuffix(" · observed missing")
            title, detail = "Missing values changed", f"{field}: {before} → {after}"
        elif measure.endswith(" · observed mean"):
            field = measure.removesuffix(" · observed mean")
            title, detail = "Observed mean changed", f"{field}: {before} → {after}"
        else:
            field = measure
            title, detail = "Observed value changed", f"{field}: {before} → {after}"
        findings.append(
            {"title": title, "detail": detail, "field": field, "basis": basis}
        )
        if len(findings) == 4:
            break

    changed_fields = {finding["field"] for finding in findings}
    for row in field_rows:
        source = next(
            (
                field
                for field in summary["fields"]
                if field_name(field, summary["metadata"]) == row["name"]
            ),
            None,
        )
        missing = (source or {}).get("missingness", {})
        if row["name"] not in changed_fields and missing.get("missing"):
            all_missing = missing.get("missing") == missing.get("denominator")
            findings.append(
                {
                    "title": (
                        "Only missing values were inspected"
                        if all_missing
                        else "Missing values were observed"
                    ),
                    "detail": (
                        row["name"]
                        if all_missing
                        else f"{row['name']}: {row['missing']}"
                    ),
                    "field": row["name"],
                    "basis": "Based on sampled evidence.",
                }
            )
        if len(findings) == 4:
            break
    return findings


def _table(headers, rows):
    head = "".join(f"<th scope='col'>{escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<div class='ps-observation-scroll'><table class='ps-observation-facts'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _change_rows(differences):
    rows = []
    for measure, before, after, basis in differences:
        label = {
            "Known shape/length": "Rows / shape",
            "Captured schema": "Fields",
        }.get(measure, measure)
        label = label.replace(" · observed missing", " · missing values")
        if basis.startswith("Cheap source metadata"):
            basis = "Source-reported shape; not a processed-row total."
        elif basis.startswith("Supplied metric change:"):
            basis = basis.replace("Supplied metric change:", "Supplied value changed by", 1)
        elif basis.startswith("This does not prove removal"):
            basis = "Based on captured fields; fields outside coverage may differ."
        rows.append((label, before, after, basis))
    return rows


def _section_icon(name):
    paths = {
        "findings": '<path d="M12 3l1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4L12 3Z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/>',
        "summary": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
        "fields": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
        "evidence": '<path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5"/>',
    }
    return (
        '<svg class="ps-observation-section__icon" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>'
    )


def _field_table(rows, *, compact=False):
    body = []
    for row in rows:
        change = (
            '<span class="ps-observation-change">Changed</span>'
            if row["changed"]
            else '<span aria-label="No comparable change">—</span>'
        )
        extra = (
            f'<td>{_count(row["inspected"])}</td><td>{escape(row["evidence"])}</td>'
            if not compact
            else ""
        )
        body.append(
            f'<tr tabindex="-1" data-observation-field-row="{escape(row["name"], quote=True)}">'
            f'<th scope="row">{escape(row["name"])}</th>'
            f'<td>{escape(row["missing"])}</td>'
            f'<td>{escape(row["range"])}</td>'
            f'<td>{escape(row["typical"])}</td><td>{change}</td>{extra}</tr>'
        )
    headers = ["Field", "Missing", "Observed range", "Typical value", "Change"]
    if not compact:
        headers += ["Values inspected", "Evidence"]
    head = "".join(f'<th scope="col">{label}</th>' for label in headers)
    return (
        '<div class="ps-observation-scroll"><table class="ps-observation-field-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _findings_html(findings):
    if not findings:
        return (
            '<div class="ps-observation-empty">'
            '<strong>No noteworthy changes to show yet</strong>'
            '<span>A comparable earlier observation may make changes available here.</span>'
            "</div>"
        )
    cards = []
    for finding in findings:
        action = ""
        if finding["field"]:
            action = (
                '<button type="button" class="ps-observation-link" '
                f'data-observation-field="{escape(finding["field"], quote=True)}">'
                "Explore field <span aria-hidden=\"true\">→</span></button>"
            )
        basis = finding["basis"].lower()
        if "metadata" in basis:
            evidence_label = "Based on source metadata."
        elif "supplied" in basis:
            evidence_label = "Based on supplied values."
        elif "captured field" in basis or "schema" in basis:
            evidence_label = "Based on captured fields."
        else:
            evidence_label = "Based on sampled evidence."
        cards.append(
            '<article class="ps-observation-finding">'
            '<span class="ps-observation-finding__mark" aria-hidden="true">▥</span>'
            '<div class="ps-observation-finding__copy">'
            f'<span class="ps-observation-finding__field">{escape(finding["field"] or "Dataset")}</span>'
            f'<strong>{escape(finding["title"])}</strong>'
            f'<span>{escape(finding["detail"])}</span>'
            f"<small>{evidence_label}</small></div>"
            f"{action}</article>"
        )
    return '<div class="ps-observation-findings">' + "".join(cards) + "</div>"


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
    useful_probes = summary.get("exploration", {}).get("useful_values", 0)
    notes = []
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
    field_rows = _field_rows(summary, differences)
    findings = _findings(summary, differences, field_rows)
    examples_html = ""
    if data["examples"]:
        examples_html = (
            '<section class="ps-observation-method__examples"><h4>Captured examples</h4>'
            '<p>Examples were explicitly enabled; up to 16 bounded values are shown.</p>'
            + _table(
                ["Field", "Position", "Captured value", "Evidence"], data["examples"]
            )
            + "</section>"
        )
    elif summary["examples_enabled"]:
        notes.append(
            "Examples were allowed, but no displayable examples were retained."
        )
    details = json.dumps(technical, ensure_ascii=False, allow_nan=False, indent=2)
    changes_html = (
        _table(["Finding", "Earlier", "Latest", "Basis"], _change_rows(differences))
        if differences
        else '<div class="ps-observation-empty"><strong>No comparable changes to display</strong><span>An earlier compatible observation is needed before PlotSrv can show a change.</span></div>'
    )
    description_html = (
        f'<p class="ps-observation-description">{escape(description)}</p>'
        if description
        else ""
    )
    explorer = render_table_explorer(
        grid_html='<div class="table-grid ps-tablegrid ps-table--rich" data-observation-grid="1"></div>',
        search_placeholder="Search fields and evidence…",
    )
    rows, fields = _dimensions(summary)
    row_value = _count(rows) if type(rows) is int else "Not available"
    size_label = f"{row_value} rows" if type(rows) is int else "Size unavailable"
    field_label = f"{_count(fields)} {'field' if fields == 1 else 'fields'}"
    mode = _observation_mode(summary)
    status = "Historical snapshot" if snapshot else "Latest observation"
    subject = "dataframe" if "dataframe" in summary["source_type"].lower() else "data"
    if findings:
        conclusion = (
            f"PlotSrv sampled this {subject} and found {len(findings)} "
            f"{'thing' if len(findings) == 1 else 'things'} worth looking at."
        )
    elif previous:
        conclusion = (
            f"PlotSrv sampled this {subject} and found no noteworthy changes "
            "in the comparable evidence."
        )
    else:
        conclusion = f"PlotSrv sampled this {subject} and prepared a summary for exploration."

    findings_section = _findings_html(findings)
    field_preview = _field_table(field_rows[:6], compact=True)
    all_fields = _field_table(field_rows)
    notes_html = "".join(f"<li>{escape(note)}</li>" for note in notes)
    technical_note = (
        f'<p class="ps-observation-method__scope">{escape(scope)}. {escape(history_note)}</p>'
        f'<p><strong>Comparison detail:</strong> {escape(message)}</p>'
        + (f"<ul>{notes_html}</ul>" if notes_html else "")
    )
    overview = f"""
      <section id="observation-panel-overview" class="ps-observation-panel" role="tabpanel" aria-labelledby="observation-tab-overview">
        <section class="ps-observation-section" aria-labelledby="observation-findings-title">
          <div class="ps-observation-section__heading">{_section_icon('findings')}<div><h3 id="observation-findings-title">Things worth looking at</h3><p>Useful changes and observations from the sampled data.</p></div></div>
          {findings_section}
        </section>
        <section class="ps-observation-section" aria-labelledby="observation-summary-title">
          <div class="ps-observation-section__heading">{_section_icon('summary')}<div><h3 id="observation-summary-title">Dataset summary</h3><p>A quick view of this observed {escape(subject)}.</p></div></div>
          <dl class="ps-observation-metrics">
            <div><dt>Rows</dt><dd>{escape(row_value)}</dd></div>
            <div><dt>Fields</dt><dd>{_count(fields)}</dd></div>
            <div><dt>Values inspected</dt><dd>{_count(inspected)}</dd></div>
            <div><dt>Mode</dt><dd>{escape(mode)}</dd></div>
          </dl>
        </section>
        <section class="ps-observation-section" aria-labelledby="observation-field-snapshot-title">
          <div class="ps-observation-section__heading ps-observation-section__heading--action">{_section_icon('fields')}<div><h3 id="observation-field-snapshot-title">Field snapshot</h3><p>A human-readable sample of fields and observed values.</p></div><button type="button" class="ps-observation-link" data-observation-tab-target="fields">View all fields <span aria-hidden="true">→</span></button></div>
          {field_preview}
        </section>
        <details class="ps-observation-method">
          <summary><span>How this observation was captured</span><small>Sampling, coverage, comparison limits and provenance</small></summary>
          <div class="ps-observation-method__body">{technical_note}{examples_html}<h4>Technical provenance</h4><pre class="plotsrv-pre plotsrv-pre--wrap">{escape(details)}</pre></div>
        </details>
      </section>"""
    html = f"""<div data-plotsrv-observation="1" class="ps-observation">
      <header class="ps-observation-header" aria-labelledby="observation-title">
        <div class="ps-observation-header__copy"><span class="ps-observation-eyebrow">Observed values</span><h2 id="observation-title">Observation</h2><p class="ps-observation-size">{escape(size_label)} · {escape(field_label)}</p>{description_html}<p class="ps-observation-conclusion">{escape(conclusion)}</p></div>
        <div class="ps-observation-header__status"><span>{escape(status)}</span><time>{escape(_captured_time(summary))}</time><button type="button" class="ps-observation-history" data-observation-history hidden>View history</button></div>
      </header>
      <nav class="ps-observation-tabs" role="tablist" aria-label="Observation sections">
        <button id="observation-tab-overview" type="button" role="tab" aria-selected="true" aria-controls="observation-panel-overview" data-observation-tab="overview">Overview</button>
        <button id="observation-tab-fields" type="button" role="tab" aria-selected="false" aria-controls="observation-panel-fields" data-observation-tab="fields" tabindex="-1">Fields</button>
        <button id="observation-tab-changes" type="button" role="tab" aria-selected="false" aria-controls="observation-panel-changes" data-observation-tab="changes" tabindex="-1">Changes</button>
        <button id="observation-tab-evidence" type="button" role="tab" aria-selected="false" aria-controls="observation-panel-evidence" data-observation-tab="evidence" tabindex="-1">Evidence</button>
      </nav>
      {overview}
      <section id="observation-panel-fields" class="ps-observation-panel" role="tabpanel" aria-labelledby="observation-tab-fields" hidden>
        <section class="ps-observation-section"><div class="ps-observation-section__heading">{_section_icon('fields')}<div><h3>Fields</h3><p>Observed ranges and representative values for every captured field.</p></div></div>{all_fields}</section>
      </section>
      <section id="observation-panel-changes" class="ps-observation-panel" role="tabpanel" aria-labelledby="observation-tab-changes" hidden>
        <section class="ps-observation-section"><div class="ps-observation-section__heading">{_section_icon('findings')}<div><h3>Changes</h3><p>Differences from the latest compatible earlier observation.</p></div></div>{changes_html}<p class="ps-observation-deeper-note">{escape(history_note)}</p></section>
      </section>
      <section id="observation-panel-evidence" class="ps-observation-panel" role="tabpanel" aria-labelledby="observation-tab-evidence" aria-label="Detailed evidence" hidden>
        <section class="ps-observation-section ps-observation-section--explorer"><div class="ps-observation-section__heading">{_section_icon('evidence')}<div><h3>Evidence explorer</h3><p>Filter, group, plot and save views of the bounded evidence behind this observation.</p></div></div>{explorer}</section>
      </section>
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
