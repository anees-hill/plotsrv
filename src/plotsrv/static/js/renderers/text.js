(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const wrapEnabled = core.loadPref(core.storageKeys.textWrapEnabled, "0") === "1";
    if (wrapEnabled) pre.classList.add("plotsrv-pre--wrap");

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";

      if (action === "wrap") {
        pre.classList.toggle("plotsrv-pre--wrap");
        core.savePref(
          core.storageKeys.textWrapEnabled,
          pre.classList.contains("plotsrv-pre--wrap") ? "1" : "0"
        );
        return;
      }

      if (action === "copy") {
        const ok = await core.copyTextToClipboard(pre.textContent || "");
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initTextToolbar = initTextToolbar;
})();