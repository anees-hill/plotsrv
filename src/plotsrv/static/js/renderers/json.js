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

  function clearJsonHits(scopeEl) {
    if (!scopeEl) return;
    const hits = scopeEl.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function getJsonRoot(root) {
    if (!root) return null;
    return root.querySelector('[data-plotsrv-json="1"]');
  }

  function getJsonPrefs() {
    if (typeof core.loadJsonPrefs === "function") {
      return core.loadJsonPrefs(config.activeViewId);
    }
    return {
      mode: "json",
      level_limit: "2",
      find_query: "",
    };
  }

  function saveJsonPrefs(nextPrefs) {
    if (typeof core.saveJsonPrefs === "function") {
      core.saveJsonPrefs(config.activeViewId, nextPrefs);
    }
  }

  function getPanels(jsonRoot) {
    if (!jsonRoot) return [];
    return Array.from(jsonRoot.querySelectorAll("[data-json-panel]"));
  }

  function getModeButtons(root) {
    return Array.from(root.querySelectorAll("[data-json-mode]"));
  }

  function applyModeButtonState(root, mode) {
    getModeButtons(root).forEach((btn) => {
      const btnMode = String(btn.getAttribute("data-json-mode") || "");
      const isActive = btnMode === mode;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function getActiveMode(root) {
    const active = root.querySelector("[data-json-mode].is-active");
    if (!active) return "json";
    return String(active.getAttribute("data-json-mode") || "json");
  }

  function getToolbarLabelByText(root, text) {
    const labels = Array.from(
      root.querySelectorAll('[data-plotsrv-toolbar="json"] .artifact-toolbar-label')
    );
    return (
      labels.find((el) => String(el.textContent || "").trim() === text) || null
    );
  }

  function syncToolbarForMode(root, mode) {
    const isText = mode === "text";

    const levelsLabel = getToolbarLabelByText(root, "Show levels");
    const levelSelect = root.querySelector("[data-json-level-limit='1']");
    const expandBtn = root.querySelector(
      '[data-plotsrv-action="expand-all"]'
    );
    const collapseBtn = root.querySelector(
      '[data-plotsrv-action="collapse-all"]'
    );

    const findLabel = getToolbarLabelByText(root, "Find");
    const findInput = root.querySelector("[data-plotsrv-json-find='1']");
    const prevBtn = root.querySelector('[data-plotsrv-action="find-prev"]');
    const nextBtn = root.querySelector('[data-plotsrv-action="find-next"]');
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");

    [
      levelsLabel,
      levelSelect,
      expandBtn,
      collapseBtn,
      findLabel,
      findInput,
      prevBtn,
      nextBtn,
      countEl,
    ].forEach((el) => {
      if (!el) return;
      el.hidden = isText;
    });

    if (findInput) {
      findInput.disabled = isText;
    }
    if (levelSelect) {
      levelSelect.disabled = isText;
    }
    if (prevBtn) {
      prevBtn.disabled = isText;
    }
    if (nextBtn) {
      nextBtn.disabled = isText;
    }
    if (expandBtn) {
      expandBtn.disabled = isText;
    }
    if (collapseBtn) {
      collapseBtn.disabled = isText;
    }
  }

  function setMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const allowed = new Set(["json", "simple", "text"]);
    const nextMode = allowed.has(mode) ? mode : "json";

    getPanels(jsonRoot).forEach((panel) => {
      const panelMode = String(panel.getAttribute("data-json-panel") || "");
      panel.hidden = panelMode !== nextMode;
    });

    applyModeButtonState(root, nextMode);
    syncToolbarForMode(root, nextMode);

    if (nextMode === "text") {
      applyTextModeContent(root);
    }

    const prefs = getJsonPrefs();
    prefs.mode = nextMode;
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

  function getPreferredTextValue(jsonRoot) {
    if (!jsonRoot) return "";

    const rawText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-raw-text") || "null"
    );
    if (typeof rawText === "string") return rawText;

    const prettyText = parseStoredJsonText(
      jsonRoot.getAttribute("data-plotsrv-json-pretty-text") || "null"
    );
    if (typeof prettyText === "string") return prettyText;

    const existing = jsonRoot.querySelector("[data-json-text-view='1']");
    return existing ? String(existing.textContent || "") : "";
  }

  function applyTextModeContent(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const textPre = jsonRoot.querySelector("[data-json-text-view='1']");
    if (!textPre) return;

    textPre.textContent = getPreferredTextValue(jsonRoot);
  }

  function getDetailsNodesForMode(root, mode) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    return Array.from(
      jsonRoot.querySelectorAll(
        '[data-json-panel="' + String(mode) + '"] details[data-json-depth]'
      )
    );
  }

  function setLevelLimit(root, rawLevelLimit) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const levelLimit = String(rawLevelLimit || "2");
    const select = root.querySelector("[data-json-level-limit='1']");
    if (select && String(select.value || "") !== levelLimit) {
      select.value = levelLimit;
    }

    const detailsNodes = getDetailsNodesForMode(root, mode);

    if (!detailsNodes.length) {
      const prefs = getJsonPrefs();
      prefs.level_limit = levelLimit;
      saveJsonPrefs(prefs);
      return;
    }

    if (levelLimit === "all") {
      detailsNodes.forEach((node) => {
        node.open = true;
      });
    } else {
      const n = Number(levelLimit);
      const limit = Number.isFinite(n) && n >= 1 ? n : 2;

      detailsNodes.forEach((node) => {
        const depth = Number(node.getAttribute("data-json-depth") || "0");
        node.open = depth < limit;
      });
    }

    const prefs = getJsonPrefs();
    prefs.level_limit = levelLimit;
    saveJsonPrefs(prefs);
  }

  function expandAll(root) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    detailsNodes.forEach((node) => {
      node.open = true;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "all";

    const prefs = getJsonPrefs();
    prefs.level_limit = "all";
    saveJsonPrefs(prefs);
  }

  function collapseAll(root) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    detailsNodes.forEach((node) => {
      const depth = Number(node.getAttribute("data-json-depth") || "0");
      node.open = depth < 1;
    });

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) select.value = "1";

    const prefs = getJsonPrefs();
    prefs.level_limit = "1";
    saveJsonPrefs(prefs);
  }

  function getSearchScope(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return null;

    const activePanel = Array.from(
      jsonRoot.querySelectorAll("[data-json-panel]")
    ).find((panel) => !panel.hidden);

    return activePanel || jsonRoot;
  }

  function setCounter(root, localState) {
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!countEl) return;

    if (!localState.hits.length) {
      countEl.textContent = "";
      return;
    }

    countEl.textContent =
      String(localState.idx + 1) + "/" + String(localState.hits.length);
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

  function runFind(root, localState) {
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const searchScope = getSearchScope(root);
    if (!input || !searchScope) return;

    const q = String(input.value || "").trim();

    const prefs = getJsonPrefs();
    prefs.find_query = q;
    saveJsonPrefs(prefs);

    clearJsonHits(searchScope);
    localState.hits = [];
    localState.idx = -1;
    setCounter(root, localState);

    if (!q) return;

    const panelMode = String(searchScope.getAttribute("data-json-panel") || "");
    if (panelMode === "text") {
      return;
    }

    const qLower = q.toLowerCase();
    const candidates = searchScope.querySelectorAll("[data-json-text]");

    candidates.forEach((el) => {
      const t = String(el.getAttribute("data-json-text") || "").toLowerCase();
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

  function restorePrefs(root) {
    const prefs = getJsonPrefs();

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

      const mode = String(btn.getAttribute("data-json-mode") || "");
      if (mode) {
        setMode(root, mode);
        runFind(root, localState);
        return;
      }

      const action = String(btn.getAttribute("data-plotsrv-action") || "");

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

    const select = root.querySelector("[data-json-level-limit='1']");
    if (select) {
      select.addEventListener("change", function () {
        setLevelLimit(root, String(select.value || "2"));
      });
    }

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
    const mode = getActiveMode(root);
    if (mode !== "text" && input && String(input.value || "").trim()) {
      runFind(root, localState);
    }
  }

  function initArtifactEnhancements(root) {
    if (!root) return;

    if (typeof renderers.initTextToolbar === "function") {
      renderers.initTextToolbar(root);
    }

    if (typeof renderers.initCodeToolbar === "function") {
      renderers.initCodeToolbar(root);
    }

    if (root.querySelector('[data-plotsrv-toolbar="json"]')) {
      initJsonToolbar(root);
    }
  }

  renderers.clearJsonHits = clearJsonHits;
  renderers.initJsonToolbar = initJsonToolbar;
  renderers.initArtifactEnhancements = initArtifactEnhancements;
})();