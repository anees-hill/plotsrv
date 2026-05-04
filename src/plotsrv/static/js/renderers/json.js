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
      pinned_values: [],
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

  function getToolbarGroup(root, name) {
    return root.querySelector('[data-json-toolbar-group="' + String(name) + '"]');
  }

  function syncToolbarForMode(root, mode) {
    const levelsGroup = getToolbarGroup(root, "levels");
    const findGroup = getToolbarGroup(root, "find");
    const pinsGroup = getToolbarGroup(root, "pins");
    const viewGroup = getToolbarGroup(root, "view");
  
    const isText = mode === "text";
  
    function setGroupVisible(el, shouldShow) {
      if (!el) return;
      el.hidden = !shouldShow;
      el.style.display = shouldShow ? "" : "none";
    }
  
    setGroupVisible(levelsGroup, !isText);
    setGroupVisible(findGroup, !isText);
    setGroupVisible(pinsGroup, !isText);
    setGroupVisible(viewGroup, true);
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
      clearJsonHits(jsonRoot);
      const localState = root._plotsrvJsonState;
      if (localState) {
        localState.hits = [];
        localState.idx = -1;
        setCounter(root, localState);
      }
      closePinnedModal(root);
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

  function getActiveMode(root) {
    const active = root.querySelector("[data-json-mode].is-active");
    if (!active) return "json";
    return String(active.getAttribute("data-json-mode") || "json");
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
    root._plotsrvCollapseState = {
      lastAction: "expand",
      preservedPinned: [],
    };
  }

  function collapseAll(root) {
    const mode = getActiveMode(root);
    if (mode === "text") return;

    const detailsNodes = getDetailsNodesForMode(root, mode);
    const expandedPinned = getExpandedPinnedPaths(root);

    const previousState = root._plotsrvCollapseState || {
      lastAction: "",
      preservedPinned: [],
    };

    const sameAsLast =
      previousState.lastAction === "collapse-preserve" &&
      Array.isArray(previousState.preservedPinned) &&
      previousState.preservedPinned.length > 0;

    detailsNodes.forEach((node) => {
      const depth = Number(node.getAttribute("data-json-depth") || "0");
      node.open = depth < 1;
    });

    if (sameAsLast) {
      previousState.preservedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, false);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-full",
        preservedPinned: [],
      };
    } else {
      expandedPinned.forEach((path) => {
        setPinnedValueExpanded(root, path, true);
      });
      root._plotsrvCollapseState = {
        lastAction: "collapse-preserve",
        preservedPinned: expandedPinned,
      };
    }

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

  function getPinnedPaths() {
    const prefs = getJsonPrefs();
    return Array.isArray(prefs.pinned_values) ? prefs.pinned_values.map(String) : [];
  }

  function setPinnedPaths(paths) {
    const prefs = getJsonPrefs();
    prefs.pinned_values = Array.from(new Set((paths || []).map(String).filter(Boolean)));
    saveJsonPrefs(prefs);
  }

  function getExpandedPinnedPaths(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return [];

    const pinned = new Set(getPinnedPaths());

    return Array.from(
      jsonRoot.querySelectorAll(".ps-json-entry.is-pinned[data-json-path]")
    )
      .map((el) => String(el.getAttribute("data-json-path") || ""))
      .filter((path) => {
        if (!path || !pinned.has(path)) return false;
        const entry = jsonRoot.querySelector(
          '[data-json-path="' + CSS.escape(path) + '"]'
        );
        return !!entry;
      });
  }

  function setPinnedValueExpanded(root, path, shouldOpen) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const entry = jsonRoot.querySelector(
      '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
    );
    if (!entry) return;

    entry.classList.toggle("is-pinned-open", shouldOpen);
  }

  function isPinned(path) {
    return new Set(getPinnedPaths()).has(String(path || ""));
  }

  function setPinnedState(root, path, shouldPin) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const btn = jsonRoot.querySelector(
      '[data-json-pin-toggle="' + CSS.escape(String(path)) + '"]'
    );
    const entry = jsonRoot.querySelector(
      '[data-json-path="' + CSS.escape(String(path)) + '"]'
    );

    if (btn) {
      btn.setAttribute("aria-pressed", shouldPin ? "true" : "false");
      btn.classList.toggle("is-pinned", shouldPin);
      btn.title = shouldPin ? "Unpin value" : "Pin value";
    }

    if (entry) {
      entry.classList.toggle("is-pinned", shouldPin);
    }
  }

  function restorePinnedStates(root) {
    const pinned = new Set(getPinnedPaths());
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const pinBtns = jsonRoot.querySelectorAll("[data-json-pin-toggle]");
    pinBtns.forEach((btn) => {
      const path = String(btn.getAttribute("data-json-pin-toggle") || "");
      setPinnedState(root, path, pinned.has(path));
    });
  }

  function getEntryFullValue(entry) {
    if (!entry) return "";
  
    const hiddenValue = entry.querySelector("[data-json-full-value-text='1']");
    if (hiddenValue) {
      return String(hiddenValue.textContent || "");
    }
  
    return String(entry.getAttribute("data-json-full-value") || "");
  }

  function buildPinnedModalList(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return "";

    const pinned = getPinnedPaths();
    if (!pinned.length) {
      return '<div class="note ps-note">No pinned values yet.</div>';
    }

    const parts = [];

    pinned.forEach((path) => {
      const entry = jsonRoot.querySelector(
        '.ps-json-entry[data-json-path="' + CSS.escape(String(path)) + '"]'
      );
      if (!entry) return;

      const key = String(entry.getAttribute("data-json-key") || path);
      const value = getEntryFullValue(entry);

      parts.push(
        '<div class="ps-json-pinneditem">' +
        '<div class="ps-json-pinneditem__meta">' +
        '<div class="ps-json-pinneditem__key">' + core.escapeHtml(key) + '</div>' +
        '<div class="ps-json-pinneditem__path">' + core.escapeHtml(path) + '</div>' +
        '</div>' +
        '<pre class="ps-json-pinneditem__value">' + core.escapeHtml(value) + '</pre>' +
        '</div>'
      );
    });

    if (!parts.length) {
      return '<div class="note ps-note">No pinned values available in this snapshot.</div>';
    }

    return parts.join("");
  }

  function openPinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    const list = jsonRoot.querySelector("[data-json-pinned-list='1']");
    if (!modal || !list) return;

    list.innerHTML = buildPinnedModalList(root);
    modal.hidden = false;
  }

  function closePinnedModal(root) {
    const jsonRoot = getJsonRoot(root);
    if (!jsonRoot) return;

    const modal = jsonRoot.querySelector("[data-json-pinned-modal='1']");
    if (!modal) return;

    modal.hidden = true;
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
    restorePinnedStates(root);
    syncToolbarForMode(root, getActiveMode(root));
  }

  function bindJsonToolbar(root, localState) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const jsonRoot = getJsonRoot(root);
    if (!toolbar || !jsonRoot) return;
    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;

    toolbar.setAttribute("data-plotsrv-bound", "1");

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const mode = String(btn.getAttribute("data-json-mode") || "");
      if (mode) {
        setMode(root, mode);
        if (mode !== "text") {
          runFind(root, localState);
        }
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
        return;
      }

      if (action === "open-pinned") {
        openPinnedModal(root);
      }
    });

    jsonRoot.addEventListener("click", function (ev) {
      const pinBtn =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pin-toggle]")
          : null;

      if (pinBtn) {
        const path = String(pinBtn.getAttribute("data-json-pin-toggle") || "");
        if (!path) return;

        const current = new Set(getPinnedPaths());
        const shouldPin = !current.has(path);

        if (shouldPin) {
          current.add(path);
        } else {
          current.delete(path);
        }

        setPinnedPaths(Array.from(current));
        setPinnedState(root, path, shouldPin);
        return;
      }

      const closeEl =
        ev.target && ev.target.closest
          ? ev.target.closest("[data-json-pinned-close]")
          : null;

      if (closeEl) {
        closePinnedModal(root);
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

    root._plotsrvJsonState = localState;

    bindJsonToolbar(root, localState);
    restorePrefs(root);
    syncToolbarForMode(root, getActiveMode(root));
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
