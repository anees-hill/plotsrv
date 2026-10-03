# Documentation maintenance

Build and check the site with:

```bash
uv run --locked --group docs python scripts/build_docs.py
```

The build validates internal links, anchors, images, and article reachability. The redirect map preserves retired URLs without duplicate articles. Do not add a subsystem to the main sidebar merely because it exists.

## Migration inventory

| Previous page | Destination |
|---|---|
| `get-started/what-is-plotsrv.md` | `index.md` |
| `get-started/installation.md` | `get-started/quick-start.md#install` |
| `get-started/configuration-basics.md` | `guides/configure-plotsrv.md` |
| `guides/python-api.md` | `reference/python-api.md` |
| `guides/cli.md` | `reference/cli.md` |
| `guides/configuration-reference.md` | `reference/configuration.md` |
| `guides/renderers.md` | `reference/supported-outputs-and-files.md` |
| `guides/view-descriptions.md` | `reference/configuration.md#view-descriptions` |
| `guides/my-views.md` | `reference/supported-outputs-and-files.md#saved-presentations` |
| `guides/ui-customisation.md` | `reference/configuration.md#ui-settings` |
| `guides/http-log-streams.md` | `reference/streams.md` |
| `guides/storage-and-history.md` | `reference/history.md` |
| `guides/observation-capture.md` | `reference/observation.md` |
| `guides/freshness.md` | `reference/configuration.md#freshness-settings` |
| `guides/checks.md` | `reference/checks.md` |
| `guides/webhooks.md` | `reference/webhooks.md` |
| `guides/tracebacks.md` | `reference/python-api.md#exception-helpers` |
| `guides/remote-publishers.md` | `reference/remote-publishing-and-security.md` |
| `guides/publisher-agent.md` | `reference/cli.md#publisher-helper` |
| `guides/publisher-ingestion.md` | `reference/remote-publishing-and-security.md` |
| `guides/configured-sources.md` | `reference/cli.md#configured-sources` |
| `guides/deployment-patterns.md` | `guides/run-on-another-machine.md` |
| `guides/public-demo-security.md` | `reference/remote-publishing-and-security.md#public-deployments` |
| `about/philosophy.md` | `index.md` |
| `about/publisher-contracts.md` | `development/publisher-server-internals.md` |
| `about/contributing.md` | `development/contributing.md` |
| `about/ui-development.md` | `development/ui-development.md` |
| `about/testing-and-benchmarks.md` | `development/testing-and-benchmarks.md` |
| `examples/index.md` | `examples/etl-pipeline.md` |

Home, Quick start, Watch files, and both examples were rewritten in place. Release notes retain their historical claims. New task guides link to exact reference rules. Ordinary developer concepts do not need tutorial introductions.

## Writing and verification

Open a guide with a command, working example, or concrete problem. Keep the normal case and one or two variations; link to reference for the exact rules. Check examples against the code before publishing. Test shell/Python examples in temporary directories, never against a production server. Preserve security and data-loss limitations beside the relevant example.

## Refresh screenshots

Install Chromium once, then capture all six scenes in both themes:

```bash
uv run --locked --group test playwright install chromium
uv run --locked --group test python scripts/capture_docs.py
```

The script starts a loopback server on an unused port, with temporary config and
storage. It publishes synthetic orders, log records, observations, and check
values through the Python API. It then operates the real browser controls. No
server responses or page content are mocked. The server and stream stop on exit.

Images go in `docs/assets/images/screenshots/`. Use `--output /tmp/plotsrv-shots`
to review a capture before replacing the committed images. Each light/dark pair
uses the same data and layout; timestamps reflect the actual capture. The status
scene uses a 1280 × 480 viewport; the other scenes use 1440 × 1080. Chromium uses
UTC, English labels, reduced motion, and a device scale factor of one.

Review both images in each pair. Wait for loaded content and settled metadata,
not a fixed sleep. Keep useful controls visible, add descriptive alt text and a
short caption, and link images to their full resolution. The documentation CSS
selects the screenshot matching the reader's theme. Keep screenshots beside the
task they explain, rather than collecting a gallery in the navigation.

See [UI development](ui-development.md) for browser assets and
[Contributing](contributing.md) for the test environment.
