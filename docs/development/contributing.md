# Contributing

```bash
git clone https://github.com/anees-hill/plotsrv.git
cd plotsrv
uv sync --locked --group dev --group test --group docs
uv run --locked python -m playwright install --with-deps chromium
```

On Linux, installing browser system dependencies may need sudo.

plotsrv is primarily maintained by one developer. Small fixes, reproducible bug
reports, useful examples, and feedback on confusing behaviour are welcome.
Describe the problem before proposing a new feature or dependency.

## Run the tests

```bash
uv run --locked pytest --benchmark-skip --cov=plotsrv --cov-report=xml
```

For a focused change, run the relevant tests first. Browser tests use real
Chromium. See [Testing and benchmarks](testing-and-benchmarks.md) for performance
checks and the distinction between benchmark fixtures and custom profiling tests.

## Change the browser UI

Edit the readable source, then rebuild and check the committed bundles:

```bash
uv run python scripts/build_ui_assets.py
uv run python scripts/build_ui_assets.py --check
```

See [UI development](ui-development.md) for source locations and screenshot capture.

## Change documentation

```bash
uv run --locked --group docs python scripts/build_docs.py
```

The build checks links, anchors, images, redirects, and article reachability.
See [Documentation maintenance](documentation.md) for the migration map and writing
rules. Guides teach a normal task; reference records exact behaviour.

## Report a bug

Include the plotsrv and Python versions, operating system, launch command, a small
reproducer, and the error or traceback. Remove private data and credentials.
A failing test is useful, but a clear reproducible report is enough.

## Read the implementation notes

- [Publisher/server internals](publisher-server-internals.md)
- [Observation internals](observation-internals.md)

Keep plotsrv easy to install and useful in an ordinary Python job. A new feature
should earn its setup and maintenance cost. Be direct and respectful in reviews.
