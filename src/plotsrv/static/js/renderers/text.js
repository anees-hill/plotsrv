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

  const MAX_COLOURIZE_CHARS = 300000;

  const LOG_TOKEN_RE =
    /\b(CRITICAL|FATAL|ERROR|EXCEPTION|TRACEBACK|WARNING|WARN|INFO|DEBUG|TRACE|SUCCESS|PASSED|PASS|FAILED|FAIL|OK|[1-5][0-9]{2})\b/gi;

  function getTextPrefs() {
    if (typeof core.loadTextPrefs === "function") {
      return core.loadTextPrefs(config.activeViewId);
    }

    return {
      wrap_enabled: false,
      reverse_enabled: false,
      colour_enabled: true,
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

  function renderedText(state) {
    const originalText =
      typeof state.originalText === "string" ? state.originalText : "";

    return state.reverseEnabled ? reverseLines(originalText) : originalText;
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

  function tokenClass(token) {
    const upper = String(token || "").toUpperCase();

    if (upper === "CRITICAL" || upper === "FATAL") {
      return "ps-log-token--critical";
    }

    if (
      upper === "ERROR" ||
      upper === "EXCEPTION" ||
      upper === "TRACEBACK" ||
      upper === "FAILED" ||
      upper === "FAIL"
    ) {
      return "ps-log-token--error";
    }

    if (upper === "WARNING" || upper === "WARN") {
      return "ps-log-token--warn";
    }

    if (upper === "INFO") {
      return "ps-log-token--info";
    }

    if (upper === "DEBUG" || upper === "TRACE") {
      return "ps-log-token--debug";
    }

    if (
      upper === "SUCCESS" ||
      upper === "PASSED" ||
      upper === "PASS" ||
      upper === "OK"
    ) {
      return "ps-log-token--success";
    }

    if (/^5[0-9]{2}$/.test(upper)) {
      return "ps-log-token--error";
    }

    if (/^4[0-9]{2}$/.test(upper)) {
      return "ps-log-token--warn";
    }

    if (/^[23][0-9]{2}$/.test(upper)) {
      return "ps-log-token--success";
    }

    if (/^1[0-9]{2}$/.test(upper)) {
      return "ps-log-token--info";
    }

    return "";
  }

  function colourizeLogText(text) {
    const s = String(text || "");

    if (s.length > MAX_COLOURIZE_CHARS) {
      return core.escapeHtml(s);
    }

    let out = "";
    let lastIndex = 0;

    LOG_TOKEN_RE.lastIndex = 0;

    let match;
    while ((match = LOG_TOKEN_RE.exec(s)) !== null) {
      const token = match[0];
      const cls = tokenClass(token);

      out += core.escapeHtml(s.slice(lastIndex, match.index));

      if (cls) {
        out +=
          '<span class="ps-log-token ' +
          cls +
          '">' +
          core.escapeHtml(token) +
          "</span>";
      } else {
        out += core.escapeHtml(token);
      }

      lastIndex = match.index + token.length;
    }

    out += core.escapeHtml(s.slice(lastIndex));
    return out;
  }

  function applyTextState(root, state, opts) {
    const options = opts || {};
    const pre = root.querySelector("[data-plotsrv-pre='1']");
    if (!pre) return;

    const text = renderedText(state);

    if (state.colourEnabled) {
      pre.innerHTML = colourizeLogText(text);
      pre.classList.add("plotsrv-pre--coloured");
    } else {
      pre.textContent = text;
      pre.classList.remove("plotsrv-pre--coloured");
    }

    pre.classList.toggle("plotsrv-pre--wrap", !!state.wrapEnabled);

    const wrapBtn = root.querySelector("[data-plotsrv-action='wrap']");
    const reverseBtn = root.querySelector("[data-plotsrv-action='reverse']");
    const colourBtn = root.querySelector("[data-plotsrv-action='colour']");

    setButtonActive(wrapBtn, state.wrapEnabled);
    setButtonActive(reverseBtn, state.reverseEnabled);
    setButtonActive(colourBtn, state.colourEnabled);

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


  function persistState(state) {
    const nextPrefs = getTextPrefs();
    nextPrefs.wrap_enabled = state.wrapEnabled;
    nextPrefs.reverse_enabled = state.reverseEnabled;
    nextPrefs.colour_enabled = state.colourEnabled;
    saveTextPrefs(nextPrefs);
  }

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    let jumpBtn = root.querySelector("[data-plotsrv-text-jump-bottom='1']");
    
    if (!jumpBtn) {
      jumpBtn = document.createElement("button");
      jumpBtn.type = "button";
      jumpBtn.className = "ps-text-jump-bottom";
      jumpBtn.setAttribute("data-plotsrv-text-jump-bottom", "1");
      jumpBtn.setAttribute("aria-label", "Scroll to bottom");
      jumpBtn.title = "Scroll to bottom";
      jumpBtn.textContent = "↓";
    
      const shell = pre.closest(".ps-text-shell") || pre.parentElement;
      if (shell) {
        shell.appendChild(jumpBtn);
      }
    }
    
    function syncJumpButton() {
      if (!jumpBtn) return;
    
      const thresholdPx = 32;
      const distanceFromBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight;
      const canScroll = pre.scrollHeight > pre.clientHeight + thresholdPx;
      const isAwayFromBottom = distanceFromBottom > thresholdPx;
    
      jumpBtn.hidden = !(canScroll && isAwayFromBottom);
    }
    
    jumpBtn.addEventListener("click", function () {
      pre.scrollTo({
        top: pre.scrollHeight,
        behavior: "smooth",
      });
    });
    
    pre.addEventListener("scroll", syncJumpButton);
    window.addEventListener("resize", syncJumpButton);
    setTimeout(syncJumpButton, 0);

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
      colourEnabled: prefs.colour_enabled !== false,
    };

    root._plotsrvTextState = state;

    applyTextState(root, state);
    setTimeout(syncJumpButton, 0);

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";

      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0); 
        return;
      }

      if (action === "reverse") {
        state.reverseEnabled = !state.reverseEnabled;
        persistState(state);
        applyTextState(root, state);
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "colour") {
        state.colourEnabled = !state.colourEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setTimeout(syncJumpButton, 0);  
        return;
      }

      if (action === "copy") {
        const ok = await core.copyTextToClipboard(renderedText(state));
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = "Copy";
        }, 900);
      }
    });
  }

  renderers.initTextToolbar = initTextToolbar;
})();
