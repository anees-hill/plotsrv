(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const THEMES = ["light", "dark", "system"];
  let returnFocus = null;

  function normalizeTheme(value) {
    const theme = String(value || "").toLowerCase();
    return THEMES.indexOf(theme) >= 0 ? theme : "light";
  }

  function currentTheme() {
    const stored = typeof core.loadPref === "function"
      ? core.loadPref(core.storageKeys.theme, "light")
      : "light";
    return normalizeTheme(stored);
  }

  function updateThemeControls(theme) {
    document.querySelectorAll("[data-theme-option]").forEach(function (button) {
      const selected = button.getAttribute("data-theme-option") === theme;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
  }

  function applyTheme(value, options) {
    const theme = normalizeTheme(value);
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme === "system" ? "light dark" : theme;
    updateThemeControls(theme);

    if (!options || options.persist !== false) {
      if (typeof core.savePref === "function") {
        core.savePref(core.storageKeys.theme, theme);
      }
    }

    window.dispatchEvent(new CustomEvent("plotsrv:themechange", {
      detail: {theme: theme},
    }));
    return theme;
  }

  function focusableElements(page) {
    return Array.from(
      page.querySelectorAll(
        "button:not([disabled]):not([hidden]), [href], " +
          "input:not([disabled]), select:not([disabled]), " +
          "textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
      )
    ).filter(function (element) {
      return !element.closest("[hidden]");
    });
  }

  function syncSettingsHeaderHeight() {
    const header = document.getElementById("site-header");
    const page = document.getElementById("settings-page");
    if (header && page && !page.hidden) {
      page.style.setProperty("--ps-settings-header-height", header.getBoundingClientRect().height + "px");
      page.style.setProperty("--ps-settings-header-padding", window.getComputedStyle(header).padding);
    }
  }

  function openSettings() {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    const close = document.getElementById("settings-close");
    if (!page) return;

    returnFocus = document.activeElement;
    updateThemeControls(normalizeTheme(
      document.documentElement.getAttribute("data-theme") || currentTheme()
    ));
    page.hidden = false;
    syncSettingsHeaderHeight();
    if (document.body) document.body.classList.add("ps-settings-open");
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    if (close) close.focus();
    else page.focus();
  }

  function closeSettings(options) {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    if (!page || page.hidden) return;

    page.hidden = true;
    if (document.body) document.body.classList.remove("ps-settings-open");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (!options || options.restoreFocus !== false) {
      if (returnFocus && typeof returnFocus.focus === "function") returnFocus.focus();
      else if (trigger) trigger.focus();
    }
  }

  function bindSettings() {
    const page = document.getElementById("settings-page");
    const trigger = document.getElementById("settings-button");
    const close = document.getElementById("settings-close");
    if (!page || !trigger || page.dataset.plotsrvBound === "1") return;

    applyTheme(currentTheme(), {persist: false});
    const header = document.getElementById("site-header");
    if (header && typeof ResizeObserver === "function") {
      new ResizeObserver(syncSettingsHeaderHeight).observe(header);
    } else {
      window.addEventListener("resize", syncSettingsHeaderHeight);
    }
    trigger.addEventListener("click", openSettings);
    if (close) close.addEventListener("click", closeSettings);
    page.querySelectorAll("[data-theme-option]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyTheme(button.getAttribute("data-theme-option"));
      });
    });

    page.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSettings();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = focusableElements(page);
      if (!focusable.length) {
        event.preventDefault();
        page.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    page.dataset.plotsrvBound = "1";
  }

  core.normalizeTheme = normalizeTheme;
  core.currentTheme = currentTheme;
  core.applyTheme = applyTheme;
  core.openSettings = openSettings;
  core.closeSettings = closeSettings;
  core.bindSettings = bindSettings;
})();
