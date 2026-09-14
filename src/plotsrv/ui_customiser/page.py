"""Small editor shell; the preview itself comes from the dashboard renderer."""

from html import escape


def page(manifest):
    css = escape(manifest["customiser_css"], quote=True)
    js = escape(manifest["customiser_js"], quote=True)
    shared = escape(manifest["css"], quote=True)
    return f"""<!doctype html><html lang="en" data-theme="light"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>plotsrv · Dashboard appearance</title><link rel="icon" href="/static/ui-images/plotsrv_icon_logo.png">
<link rel="stylesheet" href="{shared}"><link rel="stylesheet" href="{css}"><script src="{js}" defer></script>
</head><body class="customiser">
<header class="editor-heading"><img src="/static/ui-images/plotsrv_icon_logo.png" alt="plotsrv"><div><h1>Dashboard appearance</h1><p>Temporary editor · changes stay in the draft until you confirm Save.</p></div></header>
<p id="notice" role="status" aria-live="polite"></p>
<section id="login"><h2>Open your editing session</h2><p>Paste the temporary session key printed by <code>plotsrv config ui</code>. It stays in memory in this tab.</p>
<form id="unlock"><label for="session">Session key</label><input id="session" type="password" autocomplete="off" maxlength="128" required autofocus><button type="submit">Open editor</button></form></section>
<main id="editor" hidden>
<div class="scope"><strong id="config-path"></strong><span id="scope"></span><p id="preserved">Other settings, comments and instances are preserved. View lists and legacy options remain editable in YAML.</p></div>
<div class="editor-layout"><section class="preview-pane" aria-labelledby="preview-title">
<div class="preview-heading"><h2 id="preview-title">Preview</h2><label>Appearance <select id="theme"><option value="light">Light</option><option value="dark">Dark</option></select></label></div>
<p>Example data only. Choose the logo, header controls or lower bar to edit their settings.</p>
<div class="preview-tab" aria-label="Browser tab preview"><img id="preview-favicon" src="/static/ui-images/plotsrv_icon_logo.png" alt="Preview tab icon"><span id="preview-page-title"></span></div>
<iframe id="preview" title="Dashboard preview with example data" sandbox="allow-same-origin"></iframe>
<p class="muted">Preview controls select settings; they do not operate a dashboard. One logo is used in both appearances.</p>
</section><aside aria-label="Appearance settings">
<nav aria-label="Configurable regions"><button type="button" data-region="branding" aria-pressed="true">Logo &amp; header</button><button type="button" data-region="controls" aria-pressed="false">Controls</button><button type="button" data-region="footer" aria-pressed="false">Lower bar</button></nav>
<form id="settings"><div id="fields"></div><button type="submit">Update preview</button></form>
<p id="asset-policy">Uploads: still PNG/JPEG, up to 2 MiB, 2048 per side and 2 megapixels. Metadata is removed. No SVG or animation.</p><p id="asset-directory"></p><p>Existing images outside this directory and external URLs are preserved, but are not loaded by this preview.</p>
<p>Colours and theme defaults are not edited here. Dashboard appearance remains a browser preference.</p>
</aside></div>
<footer class="editor-actions"><button id="cancel" type="button">Cancel and close</button><button id="review" type="button">Review changes</button></footer>
</main>
<dialog id="review-dialog" aria-labelledby="review-title"><h2 id="review-title">Review UI settings</h2><pre id="diff" tabindex="0"></pre><p id="review-error" role="alert"></p><p>Saving creates uniquely named images and a config backup. Running services will not restart.</p><div class="dialog-actions"><button id="back" type="button" autofocus>Keep editing</button><button id="save" type="button">Save and close editor</button></div></dialog>
<section id="finished" hidden><h2 id="finished-title"></h2><p id="finished-message"></p><p>You can close this tab.</p></section>
</body></html>"""
