// src/plotsrv/static/js/renderers/text.js
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
  const config = window.PLOTSRV.config;

  function getTextPrefs() {
    if (typeof core.loadTextPrefs === "function") {
      return core.loadTextPrefs(config.activeViewId);
    }

    return {
      wrap_enabled: false,
      reverse_enabled: false,
    };
  }

  function saveTextPrefs(nextPrefs) {
    if (typeof core.saveTextPrefs === "function") {
      core.saveTextPrefs(config.activeViewId, nextPrefs);
      return;
    }

    if (core.storageKeys && typeof core.savePref === "function") {
      core.savePref(
        core.storageKeys.textWrapEnabled,
        nextPrefs.wrap_enabled ? "1" : "0"
      );
    }
  }

  function splitLinesPreserveEndings(text) {
    return String(text || "").match(/[^\n]*\n|[^\n]+/g) || [];
  }

  function reverseLines(text) {
    const lines = splitLinesPreserveEndings(text);
    return lines.reverse().join("");
  }

  function setButtonActive(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function syncReverseIndicator(root, reverseEnabled) {
    const indicator = root.querySelector("[data-plotsrv-text-reverse-indicator='1']");
    if (!indicator) return;
    indicator.hidden = !reverseEnabled;
  }

  function applyTextState(root, state, opts) {
    const options = opts || {};
    const pre = root.querySelector("[data-plotsrv-pre='1']");
    if (!pre) return;

    const originalText =
      typeof state.originalText === "string" ? state.originalText : "";

    pre.textContent = state.reverseEnabled
      ? reverseLines(originalText)
      : originalText;

    pre.classList.toggle("plotsrv-pre--wrap", !!state.wrapEnabled);

    const wrapBtn = root.querySelector("[data-plotsrv-action='wrap']");
    const reverseBtn = root.querySelector("[data-plotsrv-action='reverse']");

    setButtonActive(wrapBtn, state.wrapEnabled);
    setButtonActive(reverseBtn, state.reverseEnabled);
    syncReverseIndicator(root, state.reverseEnabled);

    if (options.scroll !== false) {
      applyInitialScroll(pre, state);
    }
  }

  function applyInitialScroll(pre, state) {
    const anchor = String(pre.getAttribute("data-plotsrv-text-anchor") || "head");

    if (state.reverseEnabled) {
      pre.scrollTop = 0;
      return;
    }

    if (anchor === "tail") {
      pre.scrollTop = pre.scrollHeight;
      return;
    }

    pre.scrollTop = 0;
  }

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    if (document.body) {
      document.body.classList.add("ps-has-text-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = getTextPrefs();

    const state = {
      originalText: pre.textContent || "",
      wrapEnabled: !!prefs.wrap_enabled,
      reverseEnabled: !!prefs.reverse_enabled,
    };

    root._plotsrvTextState = state;

    applyTextState(root, state);

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;

        const nextPrefs = getTextPrefs();
        nextPrefs.wrap_enabled = state.wrapEnabled;
        nextPrefs.reverse_enabled = state.reverseEnabled;
        saveTextPrefs(nextPrefs);

        applyTextState(root, state, { scroll: false });
        return;
      }

      if (action === "reverse") {
        state.reverseEnabled = !state.reverseEnabled;

        const nextPrefs = getTextPrefs();
        nextPrefs.wrap_enabled = state.wrapEnabled;
        nextPrefs.reverse_enabled = state.reverseEnabled;
        saveTextPrefs(nextPrefs);

        applyTextState(root, state);
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
