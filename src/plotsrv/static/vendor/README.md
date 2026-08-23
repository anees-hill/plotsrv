# Vendored browser dependencies

These files are shipped so the plotsrv UI works without internet access.

## Tabulator

- package: `tabulator-tables`
- version: `5.5.0`
- source archive: `tabulator-tables-5.5.0.tgz` from the npm registry
- upstream archive integrity: `sha512-UVe26QIaGqFfaP5wfN51zF4Vy23MNTWyvM95bF7EWGsDRQm6b2MV0wiBzakVGFj28YAgz5PvEyfqLZF415PWxw==`
- licence: MIT; see `tabulator/5.5.0/LICENSE`

Vendored file SHA-256 checksums:

```text
bb1a387ba706b8c399ec8ae94567c445f20b0d9b8297e6c16612b15fd690a132  tabulator.min.css
9fd97d87217a44afff6f14c19390e2be526dde470eeefdf3d1fe93fcc7786e48  tabulator.min.js
```

When upgrading, replace the versioned directory, update
`scripts/build_ui_assets.py`, rebuild the UI assets, and run the UI asset tests.
