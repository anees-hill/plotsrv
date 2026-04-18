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

  function clearJsonHits(tree) {
    const hits = tree.querySelectorAll(".json-hit, .json-hit-current");
    hits.forEach((el) => {
      el.classList.remove("json-hit");
      el.classList.remove("json-hit-current");
    });
  }

  function initJsonToolbar(root) {
    const toolbar = root.querySelector('[data-plotsrv-toolbar="json"]');
    const tree = root.querySelector('[data-plotsrv-json="1"]');
    const input = root.querySelector("[data-plotsrv-json-find='1']");
    const countEl = root.querySelector("[data-plotsrv-json-count='1']");
    if (!toolbar || !tree || !input) return;

    if (toolbar.getAttribute("data-plotsrv-bound") === "1") return;
    toolbar.setAttribute("data-plotsrv-bound", "1");

    const state = {
      hits: [],
      idx: -1,
    };

    function setCounter() {
      if (!countEl) return;
      if (!state.hits.length) {
        countEl.textContent = "";
        return;
      }
      countEl.textContent = `${state.idx + 1}/${state.hits.length}`;
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

    function gotoIndex(i) {
      if (!state.hits.length) return;

      state.hits.forEach((el) => el.classList.remove("json-hit-current"));
      state.idx = (i + state.hits.length) % state.hits.length;

      const el = state.hits[state.idx];
      el.classList.add("json-hit-current");
      openParents(el);
      try {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch (e) {
        el.scrollIntoView();
      }
      setCounter();
    }

    function runFind() {
      const q = String(input.value || "").trim();
      core.savePref(core.storageKeys.jsonFindQuery, q);

      clearJsonHits(tree);
      state.hits = [];
      state.idx = -1;
      setCounter();

      if (!q) return;

      const qLower = q.toLowerCase();
      const candidates = tree.querySelectorAll("[data-json-text]");
      candidates.forEach((el) => {
        const t = (el.getAttribute("data-json-text") || "").toLowerCase();
        if (!t) return;
        if (t.includes(qLower)) {
          el.classList.add("json-hit");
          state.hits.push(el);
        }
      });

      if (state.hits.length) gotoIndex(0);
    }

    const saved = core.loadPref(core.storageKeys.jsonFindQuery, "");
    if (saved && !input.value) input.value = saved;

    if (String(input.value || "").trim()) runFind();

    toolbar.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("button") : null;
      if (!btn) return;

      const action = btn.getAttribute("data-plotsrv-action") || "";
      if (action === "find-next") {
        if (!state.hits.length) runFind();
        if (state.hits.length) gotoIndex(state.idx + 1);
        return;
      }
      if (action === "find-prev") {
        if (!state.hits.length) runFind();
        if (state.hits.length) gotoIndex(state.idx - 1);
      }
    });

    input.addEventListener("input", function () {
      if (input._plotsrvTimer) clearTimeout(input._plotsrvTimer);
      input._plotsrvTimer = setTimeout(runFind, 120);
    });

    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (!state.hits.length) runFind();
        if (state.hits.length) gotoIndex(state.idx + 1);
      }
    });
  }

  renderers.clearJsonHits = clearJsonHits;
  renderers.initJsonToolbar = initJsonToolbar;
})();