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

See [UI development](ui-development.md) for screenshot capture and [Contributing](contributing.md) for the test environment.
