(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const state = window.PLOTSRV.state;
  const config = window.PLOTSRV.config;

  let pendingContentLoads = 0;
  let loadingTimer = null;
  function beginContentLoading() {
    const content = document.getElementById("view-content");
    const indicator = document.getElementById("content-loading");
    if (!content || !indicator || config.kind === "none" ||
        (config.kind === "table" && !document.getElementById("table-grid")) ||
        (config.kind === "stream" && content.dataset.contentReady === "true")) return function () {};
    pendingContentLoads += 1;
    if (pendingContentLoads === 1) {
      content.setAttribute("aria-busy", "true");
      loadingTimer = window.setTimeout(function () { indicator.hidden = false; }, 180);
    }
    let finished = false;
    return function () {
      if (finished) return;
      finished = true;
      pendingContentLoads -= 1;
      if (pendingContentLoads) return;
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
      indicator.hidden = true;
      content.setAttribute("aria-busy", "false");
      content.dataset.contentReady = "true";
    };
  }

  function waitForContentImage() {
    const image = document.getElementById("plot");
    if (!image || image.complete) return Promise.resolve();
    return new Promise(function (resolve) {
      function done() {
        image.removeEventListener("load", done);
        image.removeEventListener("error", done);
        resolve();
      }
      image.addEventListener("load", done);
      image.addEventListener("error", done);
      if (image.complete) done();
    });
  }

  function refreshChromeAfterLoad() {
    if (typeof core.configureBottomBar === "function") {
      core.configureBottomBar();
    }
    if (typeof core.refreshStatus === "function") {
      // Stream updates can arrive many times per second. Their data response
      // already carries lifecycle state, so do not mirror every event with a
      // second /status request. The first load and opening the detail modal
      // still fetch a complete status snapshot.
      if (config.kind === "stream" && state.latestStatusPayload) {
        return Promise.resolve();
      }
      return core.refreshStatus();
    }
    return Promise.resolve();
  }

  function reloadCurrentViewNow() {
    if (typeof core.setStatusMessage === "function") {
      core.setStatusMessage("");
    }

    if (document.getElementById("artifact-root")) {
      if (typeof core.loadArtifact === "function") {
        return core.loadArtifact().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("stream-grid")) {
      if (typeof core.loadStream === "function") {
        return core.loadStream().then(function (applied) {
          return refreshChromeAfterLoad().then(function () { return applied; });
        });
      }
      return Promise.resolve();
    }

    if (document.getElementById("table-grid")) {
      if (typeof core.loadTable === "function") {
        return core.loadTable().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (document.getElementById("plot")) {
      if (typeof core.refreshPlot === "function") {
        return core.refreshPlot().then(refreshChromeAfterLoad);
      }
      return Promise.resolve();
    }

    if (typeof core.refreshStatus === "function") {
      return core.refreshStatus();
    }

    return Promise.resolve();
  }

  core.reloadCurrentView = function () {
    if (state.reloadCurrentViewPromise) {
      return state.reloadCurrentViewPromise;
    }

    if (document.hidden) {
      return Promise.resolve();
    }

    const finishLoading = beginContentLoading();
    const refreshPromise = Promise.resolve().then(reloadCurrentViewNow).then(function (result) {
      return waitForContentImage().then(function () { return result; });
    });
    state.reloadCurrentViewPromise = refreshPromise;

    function clearInFlight() {
      finishLoading();
      if (state.reloadCurrentViewPromise === refreshPromise) {
        state.reloadCurrentViewPromise = null;
      }
    }

    refreshPromise.then(clearInFlight, clearInFlight);
    return refreshPromise;
  };

  core.bootstrap = function () {
    if (typeof core.bindSettings === "function") {
      core.bindSettings();
    }

    if (typeof core.bindStreamInsights === "function") {
      core.bindStreamInsights();
    }

    if (typeof core.bindStreamPauseControl === "function") {
      core.bindStreamPauseControl();
    }

    if (typeof core.bindStreamControlsDisclosure === "function") {
      core.bindStreamControlsDisclosure();
    }

    if (typeof core.bindStatusModal === "function") {
      core.bindStatusModal();
    }

    if (typeof core.bindHeaderStatus === "function") {
      core.bindHeaderStatus();
    }

    if (typeof core.bindViewDropdown === "function") {
      core.bindViewDropdown();
    }

    if (typeof core.bindHistoryControls === "function") {
      core.bindHistoryControls();
    }

    if (typeof core.bindBottomBar === "function") {
      core.bindBottomBar();
    }

    if (typeof core.bindAutoRefreshControls === "function") {
      core.bindAutoRefreshControls();
    }
    if (typeof core.bindUpdateNotifications === "function") {
      core.bindUpdateNotifications();
    }

    const finishInitialLoading = beginContentLoading();
    const loadHistoryPromise =
      typeof core.loadHistory === "function"
        ? core.loadHistory()
        : Promise.resolve();

    loadHistoryPromise
      .then(function () {
        if (typeof core.syncHistoryUi === "function") {
          core.syncHistoryUi();
        }
        return core.reloadCurrentView();
      })
      .then(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.markBrowserViewApplied === "function") {
          core.markBrowserViewApplied();
        }
        if (typeof core.showPendingSnapshotNotice === "function") {
          core.showPendingSnapshotNotice();
        }
      })
      .catch(function () {
        if (typeof core.markInitialViewLoaded === "function") core.markInitialViewLoaded();
        if (typeof core.refreshStatus === "function") {
          core.refreshStatus();
        }
      }).then(finishInitialLoading, finishInitialLoading);
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof core.bootstrap === "function") {
      core.bootstrap();
    }
  });
})();
