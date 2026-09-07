// src/plotsrv/static/js/renderers/text.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || { core: {}, renderers: {}, state: {}, config: {} };

  const core = window.PLOTSRV.core;
  const renderers = window.PLOTSRV.renderers;
  const config = window.PLOTSRV.config;
  const MAX_COLOURIZE_CHARS = 300000;
  const MAX_CLASSIFY_CHARS = 16000;
  const MAX_CLASSIFY_LINES = 80;
  const STYLE_PRESETS = [
    "auto", "plain", "http", "application", "timestamp", "syslog",
    "container", "test", "traceback", "keyvalue",
  ];
  const STYLE_LABELS = {
    auto: "Auto",
    plain: "Plain",
    http: "HTTP",
    application: "Application",
    timestamp: "Timestamp",
    syslog: "Syslog",
    container: "Container",
    test: "Test output",
    traceback: "Traceback",
    keyvalue: "Key / value",
  };

  function normalizeStylePreset(value) {
    const candidate = String(value || "").toLowerCase();
    return STYLE_PRESETS.indexOf(candidate) === -1 ? "auto" : candidate;
  }

  function getTextPrefs() {
    if (typeof core.loadTextPrefs === "function") {
      return core.loadTextPrefs(config.activeViewId);
    }
    return {
      wrap_enabled: false,
      reverse_enabled: false,
      style_preset: "auto",
      colour_enabled: true,
    };
  }

  function saveTextPrefs(nextPrefs) {
    if (typeof core.saveTextPrefs === "function") {
      core.saveTextPrefs(config.activeViewId, nextPrefs);
      return;
    }
    if (core.storageKeys && typeof core.savePref === "function") {
      core.savePref(core.storageKeys.textWrapEnabled, nextPrefs.wrap_enabled ? "1" : "0");
    }
  }

  function splitLinesPreserveEndings(text) {
    return String(text || "").match(/[^\n]*\n|[^\n]+/g) || [];
  }

  function reverseLines(text) {
    return splitLinesPreserveEndings(text).reverse().join("");
  }

  function renderedText(state) {
    const originalText = typeof state.originalText === "string" ? state.originalText : "";
    return state.reverseEnabled ? reverseLines(originalText) : originalText;
  }

  function sampledLines(text) {
    return String(text || "")
      .slice(0, MAX_CLASSIFY_CHARS)
      .split(/\r?\n/)
      .filter(function (line) { return line.trim().length > 0; })
      .slice(0, MAX_CLASSIFY_LINES);
  }

  function classifyTextStyle(text) {
    const lines = sampledLines(text);
    if (!lines.length) return "plain";

    const scores = {
      http: 0,
      application: 0,
      timestamp: 0,
      syslog: 0,
      container: 0,
      test: 0,
      traceback: 0,
      keyvalue: 0,
    };
    const severity = /\b(?:TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|CRITICAL|FATAL)\b/;
    const timestamp = /(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b)/;

    lines.forEach(function (line) {
      const hasSeverity = severity.test(line);
      const hasTimestamp = timestamp.test(line);

      if (/Traceback \(most recent call last\):/.test(line)) scores.traceback += 12;
      if (/^\s*File ["'].+?["'], line \d+/.test(line)) scores.traceback += 5;
      if (/^\s*at\s+.+:\d+(?::\d+)?\s*$/.test(line)) scores.traceback += 4;
      if (/^\s*[A-Za-z_$][\w.$]*(?:Error|Exception):/.test(line)) scores.traceback += 5;

      if (/\b(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|CONNECT|TRACE)\s+\/\S*(?:\s+HTTP\/\d(?:\.\d)?|\s+[1-5]\d\d\b)/.test(line)) {
        scores.http += 8;
      } else if (/"(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\s+\S+\s+HTTP\/\d(?:\.\d)?"\s+[1-5]\d\d\b/.test(line)) {
        scores.http += 8;
      }

      if (/^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+(?:\[\d+\])?:/.test(line)) {
        scores.syslog += 9;
      }
      if (/^\d{4}-\d{2}-\d{2}T\S+\s+(?:stdout|stderr)\s+[FP]\s+/i.test(line)) {
        scores.container += 9;
      }
      if (/^[A-Za-z0-9_.-]+\s+\|\s+/.test(line)) scores.container += 4;

      if (/\b(?:PASSED|FAILED|SKIPPED|XFAIL|XPASS)\b/.test(line)) scores.test += 4;
      if (/\btest_[A-Za-z0-9_./:-]+/.test(line) || /::[A-Za-z0-9_.\[\]-]+/.test(line)) {
        scores.test += 3;
      }
      if (/^=+\s+.*(?:passed|failed|error|skipped).*\s+=+$/i.test(line)) scores.test += 7;

      const pairs = line.match(/(?:^|\s)[A-Za-z_][\w.-]*\s*(?:=|:)\s*\S+/g);
      if (pairs) scores.keyvalue += Math.min(6, pairs.length * 3);
      if (hasTimestamp && hasSeverity) scores.timestamp += 5;
      if (hasSeverity) scores.application += 2;
      if (/^\s*(?:\[[^\]\n]{1,48}\]|[A-Za-z_][\w.-]{1,47})\s*[:|-]\s+/.test(line)) {
        scores.application += 1;
      }
    });

    const priority = [
      "traceback", "http", "syslog", "container", "test", "keyvalue",
      "timestamp", "application",
    ];
    let best = "plain";
    let bestScore = 4;
    priority.forEach(function (preset) {
      if (scores[preset] > bestScore) {
        best = preset;
        bestScore = scores[preset];
      }
    });
    return best;
  }

  function tokenClass(token) {
    const upper = String(token || "").toUpperCase();
    if (upper === "CRITICAL" || upper === "FATAL") return "ps-log-token--critical";
    if (
      upper === "ERROR" || upper === "EXCEPTION" || upper === "TRACEBACK" ||
      upper === "FAILED" || upper === "FAIL"
    ) return "ps-log-token--error";
    if (upper === "WARNING" || upper === "WARN" || /^4[0-9]{2}$/.test(upper)) {
      return "ps-log-token--warn";
    }
    if (upper === "INFO" || /^1[0-9]{2}$/.test(upper)) return "ps-log-token--info";
    if (upper === "DEBUG" || upper === "TRACE") return "ps-log-token--debug";
    if (
      upper === "SUCCESS" || upper === "PASSED" || upper === "PASS" ||
      upper === "OK" || /^[23][0-9]{2}$/.test(upper)
    ) return "ps-log-token--success";
    if (/^5[0-9]{2}$/.test(upper)) return "ps-log-token--error";
    return "";
  }

  function highlightRules(preset) {
    const rules = [];
    const add = function (regex, className) {
      rules.push({ regex: regex, className: className });
    };

    if (preset === "http") {
      add(/\b(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|CONNECT)\b/g, "ps-log-token--method");
      add(/\/(?:[^\s"'?#]+\/?)*(?:\?[^\s"']*)?/g, "ps-log-token--path");
      add(/\b[1-5][0-9]{2}\b/g, tokenClass);
    }
    if (preset === "application") {
      add(/(?:\[[^\]\n]{1,48}\]|[A-Za-z_][\w.-]{1,47})(?=\s*[:|-]\s+)/g, "ps-log-token--context");
    }
    if (preset === "syslog") {
      add(/[A-Za-z0-9_.-]+(?:\[\d+\])?(?=:)/g, "ps-log-token--context");
    }
    if (preset === "container") {
      add(/\b(?:stdout|stderr)\b/gi, function (token) {
        return token.toLowerCase() === "stderr" ? "ps-log-token--error" : "ps-log-token--stream";
      });
      add(/^[A-Za-z0-9_.-]+(?=\s+\|)/gm, "ps-log-token--context");
    }
    if (preset === "test") {
      add(/\b(?:PASSED|PASS|OK|FAILED|FAIL|ERROR|SKIPPED|XFAIL|XPASS)\b/gi, tokenClass);
      add(/\btest_[A-Za-z0-9_./:-]+/g, "ps-log-token--test");
    }
    if (preset === "traceback") {
      add(/File ["'][^"'\n]+["'], line \d+/g, "ps-log-token--file");
      add(/\bat\s+[^\n]+:\d+(?::\d+)?/g, "ps-log-token--file");
      add(/\b[A-Za-z_$][\w.$]*(?:Error|Exception)\b/g, "ps-log-token--error");
      add(/\bTraceback\b/g, "ps-log-token--error");
    }
    if (preset === "keyvalue") {
      add(/\b[A-Za-z_][\w.-]*(?=\s*(?:=|:)\s*\S)/g, "ps-log-token--key");
      add(/\b(?:true|false|null|none|yes|no|on|off)\b/gi, "ps-log-token--constant");
    }
    if (["application", "timestamp", "syslog", "container"].indexOf(preset) !== -1) {
      add(/\b(?:CRITICAL|FATAL|ERROR|EXCEPTION|WARNING|WARN|NOTICE|INFO|DEBUG|TRACE|SUCCESS)\b/gi, tokenClass);
    }
    if (["http", "application", "timestamp", "syslog", "container"].indexOf(preset) !== -1) {
      add(/\b(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b/g, "ps-log-token--timestamp");
    }
    return rules;
  }

  function collectHighlightRanges(text, rules) {
    const ranges = [];
    rules.forEach(function (rule, priority) {
      rule.regex.lastIndex = 0;
      let match;
      while ((match = rule.regex.exec(text)) !== null) {
        const token = match[0];
        const className = typeof rule.className === "function"
          ? rule.className(token)
          : rule.className;
        if (token && className) {
          ranges.push({
            start: match.index,
            end: match.index + token.length,
            className: className,
            priority: priority,
          });
        }
        if (!token) rule.regex.lastIndex += 1;
      }
    });
    ranges.sort(function (a, b) {
      return a.start - b.start || a.priority - b.priority || b.end - a.end;
    });
    const accepted = [];
    let end = -1;
    ranges.forEach(function (range) {
      if (range.start >= end) {
        accepted.push(range);
        end = range.end;
      }
    });
    return accepted;
  }

  function highlightText(text, requestedPreset) {
    const source = String(text || "");
    let preset = normalizeStylePreset(requestedPreset);
    if (preset === "auto") preset = classifyTextStyle(source);
    if (preset === "plain" || source.length > MAX_COLOURIZE_CHARS) {
      return core.escapeHtml(source);
    }

    const ranges = collectHighlightRanges(source, highlightRules(preset));
    let out = "";
    let cursor = 0;
    ranges.forEach(function (range) {
      out += core.escapeHtml(source.slice(cursor, range.start));
      out += '<span class="ps-log-token ' + range.className + '">' +
        core.escapeHtml(source.slice(range.start, range.end)) + "</span>";
      cursor = range.end;
    });
    return out + core.escapeHtml(source.slice(cursor));
  }

  function setButtonActive(btn, active) {
    if (!btn) return;
    btn.classList.toggle("is-active", !!active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }

  function syncReverseIndicator(root, reverseEnabled) {
    const indicator = root.querySelector("[data-plotsrv-text-reverse-indicator='1']");
    if (indicator) indicator.hidden = !reverseEnabled;
  }

  function resolvedStyle(state) {
    return state.stylePreset === "auto" ? state.detectedStyle : state.stylePreset;
  }

  function syncStyleControls(root, state) {
    const trigger = root.querySelector("[data-plotsrv-action='style-menu']");
    const choice = root.querySelector("[data-plotsrv-text-style-choice='1']");
    const effective = resolvedStyle(state);
    if (trigger) {
      trigger.classList.toggle("is-active", effective !== "plain");
      trigger.title = state.stylePreset === "auto"
        ? "Auto detected: " + (STYLE_LABELS[effective] || "Plain")
        : "Text highlighting: " + (STYLE_LABELS[state.stylePreset] || "Plain");
    }
    if (choice) choice.textContent = STYLE_LABELS[state.stylePreset] || "Auto";
    root.querySelectorAll("[data-plotsrv-text-style]").forEach(function (button) {
      const selected = button.getAttribute("data-plotsrv-text-style") === state.stylePreset;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-checked", selected ? "true" : "false");
    });
  }

  function setStyleMenuOpen(root, open) {
    const trigger = root.querySelector("[data-plotsrv-action='style-menu']");
    const menu = root.querySelector("[data-plotsrv-text-style-menu='1']");
    if (!trigger || !menu) return;
    menu.hidden = !open;
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      const selected = menu.querySelector("[aria-checked='true']");
      if (selected) selected.focus();
    }
  }

  function applyInitialScroll(pre, state) {
    const anchor = String(pre.getAttribute("data-plotsrv-text-anchor") || "head");
    if (state.reverseEnabled) pre.scrollTop = 0;
    else if (anchor === "tail") pre.scrollTop = pre.scrollHeight;
    else pre.scrollTop = 0;
  }

  function applyTextState(root, state, opts) {
    const options = opts || {};
    const pre = root.querySelector("[data-plotsrv-pre='1']");
    if (!pre) return;
    const text = renderedText(state);
    const effective = resolvedStyle(state);

    if (state.appliedText !== text || state.appliedStyle !== effective) {
      if (effective === "plain") {
        pre.textContent = text;
        pre.classList.remove("plotsrv-pre--coloured");
      } else {
        pre.innerHTML = highlightText(text, effective);
        pre.classList.add("plotsrv-pre--coloured");
      }
      pre.setAttribute("data-plotsrv-text-style", effective);
      state.appliedText = text;
      state.appliedStyle = effective;
    }

    pre.classList.toggle("plotsrv-pre--wrap", !!state.wrapEnabled);
    setButtonActive(root.querySelector("[data-plotsrv-action='wrap']"), state.wrapEnabled);
    setButtonActive(root.querySelector("[data-plotsrv-action='reverse']"), state.reverseEnabled);
    syncStyleControls(root, state);
    syncReverseIndicator(root, state.reverseEnabled);
    if (options.scroll !== false) applyInitialScroll(pre, state);
  }

  function persistState(state) {
    const nextPrefs = getTextPrefs();
    nextPrefs.wrap_enabled = state.wrapEnabled;
    nextPrefs.reverse_enabled = state.reverseEnabled;
    nextPrefs.style_preset = state.stylePreset;
    nextPrefs.colour_enabled = state.stylePreset !== "plain";
    saveTextPrefs(nextPrefs);
  }

  function initTextToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="text"]');
    const pre = root.querySelector('[data-plotsrv-pre="1"]');
    if (!toolbar || !pre) return;

    if (document.body) document.body.classList.add("ps-has-text-artifact");
    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const prefs = getTextPrefs();
    const originalText = pre.textContent || "";
    const stylePreset = normalizeStylePreset(
      prefs.style_preset || (prefs.colour_enabled === false ? "plain" : "auto")
    );
    const state = {
      originalText: originalText,
      wrapEnabled: !!prefs.wrap_enabled,
      reverseEnabled: !!prefs.reverse_enabled,
      stylePreset: stylePreset,
      detectedStyle: classifyTextStyle(originalText),
      appliedText: null,
      appliedStyle: null,
    };
    root._plotsrvTextState = state;
    applyTextState(root, state);

    toolbar.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;
      const selectedStyle = btn.getAttribute("data-plotsrv-text-style");
      if (selectedStyle) {
        state.stylePreset = normalizeStylePreset(selectedStyle);
        persistState(state);
        applyTextState(root, state, { scroll: false });
        setStyleMenuOpen(root, false);
        return;
      }

      const action = btn.getAttribute("data-plotsrv-action") || "";
      if (action === "style-menu") {
        setStyleMenuOpen(root, btn.getAttribute("aria-expanded") !== "true");
        return;
      }
      if (action === "wrap") {
        state.wrapEnabled = !state.wrapEnabled;
        persistState(state);
        applyTextState(root, state, { scroll: false });
        return;
      }
      if (action === "reverse") {
        state.reverseEnabled = !state.reverseEnabled;
        persistState(state);
        applyTextState(root, state);
        return;
      }
      if (action === "copy") {
        const ok = await core.copyTextToClipboard(renderedText(state));
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(function () { btn.textContent = "Copy"; }, 900);
      }
    });

    toolbar.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        setStyleMenuOpen(root, false);
        const trigger = root.querySelector("[data-plotsrv-action='style-menu']");
        if (trigger) trigger.focus();
      }
    });
    document.addEventListener("click", function closeDetachedMenu(ev) {
      if (!root.isConnected) {
        document.removeEventListener("click", closeDetachedMenu);
        return;
      }
      const control = root.querySelector(".ps-text-style-control");
      if (control && !control.contains(ev.target)) setStyleMenuOpen(root, false);
    });
  }

  renderers.classifyTextStyle = classifyTextStyle;
  renderers.highlightText = highlightText;
  renderers.textStylePresets = STYLE_PRESETS.slice();
  renderers.initTextToolbar = initTextToolbar;
})();
