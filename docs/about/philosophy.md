---
icon: lucide/lightbulb
---

# Philosophy

```text
Cheap, reliable observability with minimal code.
```

Many scripts, pipelines, experiments, and batch jobs produce useful information as they run: tables, plots, logs, status summaries, validation results, reports, exceptions, and intermediate data.

Some of these outputs are created deliberately for observability: a status dictionary, a validation report, a summary table, or a plot intended to show how a process is behaving.

Others already exist as part of the normal workflow. They may live briefly in memory, help the code do its job, and then disappear.

`plotsrv` is designed to make useful outputs easy to surface, whether they are created specifically for observability or already exist as part of the workflow.

## Cheap observability

Developer experience is central to `plotsrv`.

Observability for Python processes should be cheap.

“Cheap” means:

- little code to add
- little infrastructure to run
- little configuration required
- useful defaults out of the box
- no need to build a custom dashboard

A function can be wrapped with `@ps.view(...)`, or an object can be published with `ps.publish_view(...)`, and plotsrv handles the rest where possible.

## Sensible defaults, optional control

plotsrv should make reasonable choices about:

- renderer selection
- truncation limits
- table handling
- file rendering
- storage behaviour
- freshness display
- UI organisation

When more control is needed, it should be available through one clear place: `plotsrv.yaml`.

The goal is not to make users configure everything. The goal is to let users configure what matters.

## Lightweight by design

plotsrv is designed to stay lightweight.

It should be quick to start, easy to run, and practical to use alongside ordinary scripts and jobs.

It is not trying to replace:

- Grafana
- Prometheus
- MLflow
- Weights & Biases
- a BI platform
- a custom dashboard application

plotsrv is aimed at a different space: the gap between `print()`, log files, notebooks, saved artifacts, and full observability platforms.


In short: plotsrv should make useful outputs easier to observe without making the underlying code feel less ordinary.
