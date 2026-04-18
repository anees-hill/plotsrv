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
    autoRefreshEnabled: "plotsrv:v1:auto_refresh_enabled",
    autoRefreshInterval: "plotsrv:v1:auto_refresh_interval",
    textWrapEnabled: "plotsrv:v1:text_wrap_enabled",
    jsonFindQuery: "plotsrv:v1:json_find_query",
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
})();