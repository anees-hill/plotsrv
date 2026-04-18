(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const renderers = window.PLOTSRV.renderers;

  function initCodeToolbar(root) {
    // Reserved for later phases.
    return root;
  }

  renderers.initCodeToolbar = initCodeToolbar;
})();