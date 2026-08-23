---
icon: lucide/blocks
---

# UI development

The browser UI has no runtime CDN dependency. Tabulator 5.5.0 is vendored under
`src/plotsrv/static/vendor/` with its licence, and plotsrv's readable CSS and
JavaScript sources remain under `static/css/` and `static/js/`.

After changing a UI source file, rebuild the committed, fingerprinted assets:

```bash
python scripts/build_ui_assets.py
python scripts/build_ui_assets.py --check
```

The build is deliberately a small Python script rather than a Node toolchain.
It concatenates files in an explicit dependency order and writes
`static/dist/manifest.json`; packaged HTML only references files from that
manifest. Keep source modules focused and update the ordered source list when
adding one.

Rich table pages load three static resources: the shared CSS bundle, the local
Tabulator script, and the plotsrv JavaScript bundle. Other pages load only the
two plotsrv bundles.

## Python boundaries

The main application modules retain their established public and test-facing
imports, while stable internal concerns live separately:

| Module | Responsibility |
| --- | --- |
| `cli_parser.py` | CLI argument and help structure |
| `cli.py` | command execution and orchestration |
| `http_publish.py` | publish admission and rejection reporting |
| `http_security.py` | local-request enforcement |
| `http_snapshots.py` | snapshot and artifact response shaping |
| `file_backed_loads.py` | bounded file-preview admission |
| `view_coercion.py` | Python object type coercion for server refreshes |

The watch loop remains in `runtime.py`, and server lifecycle state remains in
`server.py`. Move those only as part of a designed service abstraction; their
state and compatibility behavior should not be split opportunistically during
UI work.
