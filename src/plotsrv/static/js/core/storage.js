// src/plotsrv/static/js/core/storage.js
(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  core.storageKeys = {
    autoRefreshEnabled: "plotsrv:v2:auto_refresh_enabled",
    autoRefreshInterval: "plotsrv:v2:auto_refresh_interval",
    textWrapEnabled: "plotsrv:v1:text_wrap_enabled",
    jsonFindQuery: "plotsrv:v1:json_find_query",
    tablePrefsPrefix: "plotsrv:v2:table_prefs:",
    jsonPrefsPrefix: "plotsrv:v2:json_prefs:",
  };

  core.loadPref = function (key, fallbackValue) {
    try {
      const val = localStorage.getItem(key);
      return val == null ? fallbackValue : val;
    } catch (e) {
      return fallbackValue;
    }
  };

  core.savePref = function (key, value) {
    try {
      localStorage.setItem(key, String(value));
    } catch (e) {
      // ignore
    }
  };

  core.getTablePrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.tablePrefsPrefix + safeViewId;
  };

  core.loadTablePrefs = function (viewId) {
    const fallback = {
      column_order: [],
      hidden_fields: [],
      search_query: "",
      header_filters: {},
    };

    try {
      const raw = localStorage.getItem(core.getTablePrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      const headerFilters =
        parsed.header_filters && typeof parsed.header_filters === "object"
          ? parsed.header_filters
          : {};

      const cleanHeaderFilters = {};
      for (const [key, value] of Object.entries(headerFilters)) {
        cleanHeaderFilters[String(key)] = String(value ?? "");
      }

      return {
        column_order: Array.isArray(parsed.column_order)
          ? parsed.column_order.map(String)
          : [],
        hidden_fields: Array.isArray(parsed.hidden_fields)
          ? parsed.hidden_fields.map(String)
          : [],
        search_query:
          typeof parsed.search_query === "string" ? parsed.search_query : "",
        header_filters: cleanHeaderFilters,
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveTablePrefs = function (viewId, prefs) {
    const headerFilters = {};
    if (prefs && prefs.header_filters && typeof prefs.header_filters === "object") {
      for (const [key, value] of Object.entries(prefs.header_filters)) {
        headerFilters[String(key)] = String(value ?? "");
      }
    }

    const payload = {
      column_order: Array.isArray(prefs && prefs.column_order)
        ? prefs.column_order.map(String)
        : [],
      hidden_fields: Array.isArray(prefs && prefs.hidden_fields)
        ? prefs.hidden_fields.map(String)
        : [],
      search_query:
        prefs && typeof prefs.search_query === "string"
          ? prefs.search_query
          : "",
      header_filters: headerFilters,
    };

    try {
      localStorage.setItem(
        core.getTablePrefsKey(viewId),
        JSON.stringify(payload)
      );
    } catch (e) {
      // ignore
    }
  };

  core.clearTablePrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getTablePrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };

  core.getJsonPrefsKey = function (viewId) {
    const safeViewId = String(viewId || "default").trim() || "default";
    return core.storageKeys.jsonPrefsPrefix + safeViewId;
  };

  core.loadJsonPrefs = function (viewId) {
    const fallback = {
      mode: "json",
      level_limit: "2",
      find_query: "",
      pinned_values: [],
    };

    try {
      const raw = localStorage.getItem(core.getJsonPrefsKey(viewId));
      if (!raw) return fallback;

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return fallback;

      return {
        mode:
          typeof parsed.mode === "string" && parsed.mode
            ? parsed.mode
            : fallback.mode,
        level_limit:
          typeof parsed.level_limit === "string" && parsed.level_limit
            ? parsed.level_limit
            : fallback.level_limit,
        find_query:
          typeof parsed.find_query === "string"
            ? parsed.find_query
            : fallback.find_query,
        pinned_values: Array.isArray(parsed.pinned_values)
          ? parsed.pinned_values.map(String)
          : [],
      };
    } catch (e) {
      return fallback;
    }
  };

  core.saveJsonPrefs = function (viewId, prefs) {
    const payload = {
      mode:
        prefs && typeof prefs.mode === "string" && prefs.mode
          ? prefs.mode
          : "json",
      level_limit:
        prefs && typeof prefs.level_limit === "string" && prefs.level_limit
          ? prefs.level_limit
          : "2",
      find_query:
        prefs && typeof prefs.find_query === "string"
          ? prefs.find_query
          : "",
      pinned_values: Array.isArray(prefs && prefs.pinned_values)
        ? Array.from(new Set(prefs.pinned_values.map(String)))
        : [],
    };

    try {
      localStorage.setItem(core.getJsonPrefsKey(viewId), JSON.stringify(payload));
    } catch (e) {
      // ignore
    }
  };

  core.clearJsonPrefs = function (viewId) {
    try {
      localStorage.removeItem(core.getJsonPrefsKey(viewId));
    } catch (e) {
      // ignore
    }
  };
})();