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

  const KEYWORDS = new Set([
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "case",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "match",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
  ]);

  const CONSTANTS = new Set(["True", "False", "None", "Ellipsis", "NotImplemented"]);

  const BUILTINS = new Set([
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "dict",
    "dir",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "open",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
  ]);

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

  function isIdentStart(ch) {
    return /[A-Za-z_]/.test(ch);
  }

  function isIdentPart(ch) {
    return /[A-Za-z0-9_]/.test(ch);
  }

  function consumeString(line, start) {
    const quote = line[start];
    const isTriple =
      line[start + 1] === quote &&
      line[start + 2] === quote;

    let i = start + (isTriple ? 3 : 1);

    while (i < line.length) {
      if (line[i] === "\\") {
        i += 2;
        continue;
      }

      if (isTriple) {
        if (
          line[i] === quote &&
          line[i + 1] === quote &&
          line[i + 2] === quote
        ) {
          return i + 3;
        }
        i += 1;
        continue;
      }

      if (line[i] === quote) {
        return i + 1;
      }

      i += 1;
    }

    return line.length;
  }

  function consumeNumber(line, start) {
    const m = line.slice(start).match(/^(0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d[\d_]*)?j?)/);
    return m ? start + m[0].length : start + 1;
  }

  function highlightPythonLine(line) {
    let out = "";
    let i = 0;

    while (i < line.length) {
      const ch = line[i];

      if (ch === "#") {
        out += '<span class="ps-code-token ps-code-token--comment">' +
          escapeHtml(line.slice(i)) +
          "</span>";
        break;
      }

      if (ch === "'" || ch === '"') {
        const end = consumeString(line, i);
        out += '<span class="ps-code-token ps-code-token--string">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (ch === "@" && isIdentStart(line[i + 1] || "")) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        out += '<span class="ps-code-token ps-code-token--decorator">' +
          escapeHtml(line.slice(i, j)) +
          "</span>";
        i = j;
        continue;
      }

      if (/[0-9]/.test(ch)) {
        const end = consumeNumber(line, i);
        out += '<span class="ps-code-token ps-code-token--number">' +
          escapeHtml(line.slice(i, end)) +
          "</span>";
        i = end;
        continue;
      }

      if (isIdentStart(ch)) {
        let j = i + 1;
        while (j < line.length && isIdentPart(line[j])) j += 1;

        const word = line.slice(i, j);
        let klass = "";

        if (KEYWORDS.has(word)) klass = "ps-code-token--keyword";
        else if (CONSTANTS.has(word)) klass = "ps-code-token--constant";
        else if (BUILTINS.has(word)) klass = "ps-code-token--builtin";

        if (klass) {
          out += '<span class="ps-code-token ' + klass + '">' +
            escapeHtml(word) +
            "</span>";
        } else {
          out += escapeHtml(word);
        }

        i = j;
        continue;
      }

      out += escapeHtml(ch);
      i += 1;
    }

    return out;
  }

  function renderCode(root, state) {
    const pre = root.querySelector("[data-plotsrv-code-pre='1']");
    const code = root.querySelector("[data-plotsrv-code-content='1']");
    if (!pre || !code) return;

    const lines = splitLines(state.originalText);
    const parts = [];

    for (let i = 0; i < lines.length; i += 1) {
      const rawLine = lines[i];
      const lineHtml = state.highlightEnabled
        ? highlightPythonLine(rawLine)
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

    code.innerHTML = parts.join("");
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

    const state = {
      originalText: code.textContent || "",
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
