---
icon: lucide/git-pull-request
---

# Contributing

Contributions are welcome.

`plotsrv` is still early, so the most useful contributions are:

- renderers (UI)
- renderer features (UI)
- bug reports
- small fixes
- examples
- feedback on confusing behaviour

## Project philosophy

plotsrv aims to provide cheap observability for Python processes.

Contributions should generally support the [project philosophy](philosophy.md):

## Reporting issues

When reporting a bug, include:

- plotsrv version
- Python version
- operating system
- how plotsrv was launched
- a small code example if possible
- the error message or traceback

## Suggesting features

Feature requests are welcome.

- what problem the feature solves
- what workflow it supports
- why existing plotsrv behaviour is not enough
- whether it fits lightweight observability

## Development setup

Clone the repository:

```bash
git clone https://github.com/anees-hill/plotsrv.git
cd plotsrv
```

Install the project for development:

```bash
uv sync --group dev --group test --group docs
```

Run tests:

```bash
uv run pytest
```

Run linting:

## Compatibility

plotsrv should remain easy to install and run.

Avoid adding heavy dependencies unless they are clearly justified. Optional features should generally remain optional.

## Conduct

Please be respectful and constructive.

The project is early, and feedback is welcome when it helps make plotsrv clearer, simpler, faster, or more useful.
