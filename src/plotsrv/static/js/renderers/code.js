// src/plotsrv/static/js/renderers/code.js
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

  function prefsKey() {
    const viewId = String(config.activeViewId || "default").trim() || "default";
    return "plotsrv:v2:code_prefs:" + viewId;
  }

  function loadCodePrefs() {
    const fallback = {
      wrap_enabled: false,
      highlight_enabled: true,
      line_numbers_enabled: true,
    };

    try {
      const raw = localStorage.getItem(prefsKey());
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        wrap_enabled:
          typeof parsed.wrap_enabled === "boolean"
            ? parsed.wrap_enabled
            : fallback.wrap_enabled,
        highlight_enabled:
          typeof parsed.highlight_enabled === "boolean"
            ? parsed.highlight_enabled
            : fallback.highlight_enabled,
        line_numbers_enabled:
          typeof parsed.line_numbers_enabled === "boolean"
            ? parsed.line_numbers_enabled
            : fallback.line_numbers_enabled,
      };
    } catch (e) {
      return fallback;
    }
  }

  function saveCodePrefs(prefs) {
    try {
      localStorage.setItem(
        prefsKey(),
        JSON.stringify({
          wrap_enabled: !!(prefs && prefs.wrap_enabled),
          highlight_enabled:
            prefs && typeof prefs.highlight_enabled === "boolean"
              ? prefs.highlight_enabled
              : true,
          line_numbers_enabled:
            prefs && typeof prefs.line_numbers_enabled === "boolean"
              ? prefs.line_numbers_enabled
              : true,
        })
      );
    } catch (e) {
      // ignore
    }
  }

  function escapeHtml(s) {
    if (core && typeof core.escapeHtml === "function") {
      return core.escapeHtml(s);
    }

    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function splitLines(text) {
    const normalised = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalised.split("\n");

    if (lines.length > 1 && lines[lines.length - 1] === "") {
      lines.pop();
    }

    return lines.length ? lines : [""];
  }

  function renderCode(root, state) {
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");
    if (!pre || !code) return;

    const lines = splitLines(state.originalText);
    const parts = [];
    const colouredLines = state.highlightedHtml ? splitLines(state.highlightedHtml) : null;

    for (let i = 0; i < lines.length; i += 1) {
      const rawLine = lines[i];
      const lineHtml = state.highlightEnabled && colouredLines
        ? colouredLines[i] || ""
        : escapeHtml(rawLine);

      parts.push(
        '<span class="ps-code-line" data-line="' +
          String(i + 1) +
          '"><span class="ps-code-line__num">' +
          String(i + 1) +
          '</span><span class="ps-code-line__text">' +
          lineHtml +
          "</span></span>"
      );
    }

    if (state.appliedHighlight !== state.highlightEnabled) {
      code.innerHTML = parts.join("");
      state.appliedHighlight = state.highlightEnabled;
    }
    pre.classList.toggle("ps-code-pre--wrap", !!state.wrapEnabled);
    pre.classList.toggle(
      "ps-code-pre--no-lines",
      !state.lineNumbersEnabled
    );

    setButtonState(
      root.querySelector("[data-plotsrv-code-action='wrap']"),
      state.wrapEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='highlight']"),
      state.highlightEnabled
    );
    setButtonState(
      root.querySelector("[data-plotsrv-code-action='lines']"),
      state.lineNumbersEnabled
    );
  }

  function setButtonState(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function initCodeToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="code"]');
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");

    if (!toolbar || !pre || !code) return;

    if (document.body) {
      document.body.classList.add("ps-has-code-artifact");
    }

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = loadCodePrefs();
    try { if (!localStorage.getItem(prefsKey())) prefs.highlight_enabled = code.getAttribute("data-plotsrv-code-default") !== "0"; } catch (_) {}

    let originalText = code.textContent || "";
    try { if (code.hasAttribute("data-plotsrv-code-raw")) originalText = JSON.parse(code.getAttribute("data-plotsrv-code-raw")); } catch (_) {}
    const state = {
      originalText,
      highlightedHtml: code.getAttribute("data-plotsrv-code-highlighted") === "1" ? code.innerHTML : null,
      appliedHighlight: null,
      wrapEnabled: !!prefs.wrap_enabled,
      highlightEnabled: !!prefs.highlight_enabled,
      lineNumbersEnabled: !!prefs.line_numbers_enabled,
    };

    root._plotsrvCodeState = state;
    renderCode(root, state);

    toolbar.addEventListener("click", async function (ev) {
      const btn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-plotsrv-code-action]")
          : null;

      if (!btn) return;

      const action = String(btn.getAttribute("data-plotsrv-code-action") || "");

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "highlight") {
        state.highlightEnabled = !state.highlightEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "lines") {
        state.lineNumbersEnabled = !state.lineNumbersEnabled;
        saveCodePrefs({
          wrap_enabled: state.wrapEnabled,
          highlight_enabled: state.highlightEnabled,
          line_numbers_enabled: state.lineNumbersEnabled,
        });
        renderCode(root, state);
        return;
      }

      if (action === "copy") {
        const ok =
          core && typeof core.copyTextToClipboard === "function"
            ? await core.copyTextToClipboard(state.originalText)
            : false;

        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(function () {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initCodeToolbar = initCodeToolbar;
})();
