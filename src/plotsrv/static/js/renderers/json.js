// src/plotsrv/static/js/renderers/json.js
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

  function clearJsonHits(tree) {
    const hits = tree.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function getJsonRoot(root) {
    if (!root) return null;
    return root.querySelector('[data-plotsrv-json="1"]');
  }

  function loadJsonPrefs() {
    if (typeof core.loadJsonPrefs !== "function") {
      return {
        mode: "json",
        level_limit: "2",
        find_query: "",
      };
    }
    return core.loadJsonPrefs(config.activeViewId);
  }

  function saveJsonPrefs(nextPrefs) {
    if (typeof core.saveJsonPrefs !== "function") return;
    core.saveJsonPrefs(config.activeViewId, nextPrefs);
  }

  function getActivePanel(jsonRoot) {
    if (!jsonRoot) return null;
    return jsonRoot.querySelector('.ps-json-panel:not([hidden])');
  }

  function getModeButtons(root) {
    return root.querySelectorAll("[data-json-mode]");
  }

  function setMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const panels = jsonRoot.querySelectorAll("[data-json-panel]");
    panels.forEach((panel) => {
      const panelMode = panel.getAttribute("data-json-panel") || "";
      panel.hidden = panelMode !== mode;
    });

    const btns = getModeButtons(root);
    btns.forEach((btn) => {
      const btnMode = btn.getAttribute("data-json-mode") || "";
      btn.classList.toggle("is-active", btnMode === mode);
      btn.setAttribute("aria-pressed", btnMode === mode ? "true" : "false");
    });

    const prefs = loadJsonPrefs();
    prefs.mode = mode;
    saveJsonPrefs(prefs);
  }

  function parseStoredJsonText(raw) {
    if (typeof raw !== "string" || !raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function getTextValue(jsonRoot) {
    if (!jsonRoot) return "";
    const rawText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-raw-text") || "null"
    );
    if (typeof rawText === "string") return rawText;

    const prettyText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-pretty-text") || "null"
    );
    if (typeof prettyText === "string") return prettyText;

    const textPre = jsonRoot.querySelector("[data-json-text-view='1']");
    return textPre ? String(textPre.textContent || "") : "";
  }

  function applyTextModeContent(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const pre = jsonRoot.querySelector("[data-json-text-view='1']");
    if (!pre) return;

    pre.textContent = getTextValue(jsonRoot);
  }

  function setLevelLimit(root, levelLimit) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select && String(select.value || "") !== String(levelLimit || "2")) {
      select.value = String(levelLimit || "2");
    }

    const richPanel = jsonRoot.querySelector('[data-json-panel="json"]');
    if (!richPanel) return;

    const detailsNodes = richPanel.querySelectorAll("details[data-json-depth]");

    if (String(levelLimit) === "all") {
      detailsNodes.forEach((node) => {
        node.open = true;
      });
    } else {
      const limit = Number(levelLimit);
      if (!Number.isFinite(limit) || limit < 1) return;

      detailsNodes.forEach((node) => {
        const depth = Number(node.getAttribute("data-json-depth") || "0");
        node.open = depth < limit;
      });
    }

    const prefs = loadJsonPrefs();
    prefs.level_limit = String(levelLimit || "2");
    saveJsonPrefs(prefs);
  }

  function expandAll(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;
    const detailsNodes = jsonRoot.querySelectorAll(
      '[data-json-panel="json"] details[data-json-depth]'
    );
    detailsNodes.forEach((node) => {
      node.open = true;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "all";

    const prefs = loadJsonPrefs();
    prefs.level_limit = "all";
    saveJsonPrefs(prefs);
  }

  function collapseAll(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;
    const detailsNodes = jsonRoot.querySelectorAll(
      '[data-json-panel="json"] details[data-json-depth]'
    );
    detailsNodes.forEach((node) => {
      const depth = Number(node.getAttribute("data-json-depth") || "0");
      node.open = depth < 1;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "1";

    const prefs = loadJsonPrefs();
    prefs.level_limit = "1";
    saveJsonPrefs(prefs);
  }

  function runFind(root, localState) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!input) return;

    const activePanel = getActivePanel(jsonRoot);
    if (!activePanel) return;

    const q = String(input.value || "").trim();
    const prefs = loadJsonPrefs();
    prefs.find_query = q;
    saveJsonPrefs(prefs);

    clearJsonHits(jsonRoot);
    localState.hits = [];
    localState.idx = -1;

    if (countEl) countEl.textContent = "";

    if (!q) return;

    // Text mode intentionally doesn't do full-text highlight yet.
    if ((activePanel.getAttribute("data-json-panel") || "") === "text") {
      return;
    }

    const qLower = q.toLowerCase();
    const candidates = activePanel.querySelectorAll("[data-json-text]");

    candidates.forEach((el) => {
      const t = (el.getAttribute("data-json-text") || "").toLowerCase();
      if (!t) return;
      if (t.includes(qLower)) {
        el.classList.add("json-hit");
        localState.hits.push(el);
      }
    });

    if (localState.hits.length) {
      gotoIndex(root, localState, 0);
    }
  }

  function setCounter(root, localState) {
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!countEl) return;

    if (!localState.hits.length) {
      countEl.textContent = "";
      return;
    }

    countEl.textContent = String(localState.idx + 1) + "/" + String(localState.hits.length);
  }

  function openParents(el) {
    let cur = el;
    while (cur) {
      const det = core.findNearest(cur, "details");
      if (!det) break;
      det.open = true;
      cur = det.parentElement;
    }
  }

  function gotoIndex(root, localState, i) {
    if (!localState.hits.length) return;

    localState.hits.forEach((el) => el.classList.remove("json-hit-current"));
    localState.idx = (i + localState.hits.length) % localState.hits.length;

    const el = localState.hits[localState.idx];
    el.classList.add("json-hit-current");
    openParents(el);

    try {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) {
      el.scrollIntoView();
    }

    setCounter(root, localState);
  }

  function restorePrefs(root) {
    const prefs = loadJsonPrefs();

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.value = prefs.find_query || "";
    }

    applyTextModeContent(root);
    setMode(root, prefs.mode || "json");
    setLevelLimit(root, prefs.level_limit || "2");
  }

  function bindJsonToolbar(root, localState) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    if (!toolbar) return;

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";
      const mode = btn.getAttribute("data-json-mode") || "";

      if (mode) {
        setMode(root, mode);
        runFind(root, localState);
        return;
      }

      if (action === "expand-all") {
        expandAll(root);
        return;
      }

      if (action === "collapse-all") {
        collapseAll(root);
        return;
      }

      if (action === "find-next") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        return;
      }

      if (action === "find-prev") {
        if (!localState.hits.length) runFind(root, localState);
        if (localState.hits.length) gotoIndex(root, localState, localState.idx - 1);
      }
    });

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input) {
      input.addEventListener("input", function () {
        if (input._plotsrvTimer) clearTimeout(input._plotsrvTimer);
        input._plotsrvTimer = setTimeout(function () {
          runFind(root, localState);
        }, 120);
      });

      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (!localState.hits.length) runFind(root, localState);
          if (localState.hits.length) gotoIndex(root, localState, localState.idx + 1);
        }
      });
    }

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) {
      select.addEventListener("change", function () {
        setLevelLimit(root, String(select.value || "2"));
      });
    }
  }

  function initJsonToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;

    const localState = {
      hits: [],
      idx: -1,
    };

    bindJsonToolbar(root, localState);
    restorePrefs(root);

    const input = root.querySelector("[data-plotsrv-json-find='1']");
    if (input && String(input.value || "").trim()) {
      runFind(root, localState);
    }
  }

  renderers.clearJsonHits = clearJsonHits;
  renderers.initJsonToolbar = initJsonToolbar;
})();