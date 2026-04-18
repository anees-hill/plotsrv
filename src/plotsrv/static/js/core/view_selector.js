(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  function bindViewDropdown() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (wrap) {
      const btn = wrap.querySelector(".ps-viewselect__btn");
      const menu = wrap.querySelector(".ps-viewselect__menu");
      if (!btn || !menu) return;

      function openMenu() {
        menu.hidden = false;
        btn.setAttribute("aria-expanded", "true");
        try {
          menu.focus();
        } catch (e) {
          // ignore
        }
      }

      function closeMenu() {
        menu.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }

      btn.addEventListener("click", function () {
        if (menu.hidden) openMenu();
        else closeMenu();
      });

      document.addEventListener("click", function (ev) {
        if (!wrap.contains(ev.target)) closeMenu();
      });

      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeMenu();
      });

      menu.addEventListener("click", function (ev) {
        const item = ev.target && ev.target.closest
          ? ev.target.closest("[data-plotsrv-view]")
          : null;
        if (!item) return;

        const v = item.getAttribute("data-plotsrv-view");
        if (!v) return;

        if (typeof core.saveAutoRefreshState === "function") {
          core.saveAutoRefreshState();
        }

        closeMenu();
        window.location.href = "/?view=" + encodeURIComponent(v);
      });

      return;
    }

    const sel = document.getElementById("view-select");
    if (!sel) return;

    sel.addEventListener("change", function () {
      if (typeof core.saveAutoRefreshState === "function") {
        core.saveAutoRefreshState();
      }
      const v = sel.value;
      window.location.href = "/?view=" + encodeURIComponent(v);
    });
  }

  core.bindViewDropdown = bindViewDropdown;
})();