(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;

  // Fixed mobile panels must follow the visible area when browser chrome or
  // the on-screen keyboard changes it. Callers subscribe only while open.
  core.trackMobileViewport = function (element) {
    const viewport = window.visualViewport;
    const properties = ["top", "left", "width", "height"];
    function update() {
      const mobile = window.matchMedia("(max-width: 640px)").matches;
      const values = viewport
        ? [viewport.offsetTop, viewport.offsetLeft, viewport.width, viewport.height]
        : [0, 0, window.innerWidth, window.innerHeight];
      properties.forEach(function (name, index) {
        const property = "--ps-mobile-viewport-" + name;
        if (mobile) element.style.setProperty(property, values[index] + "px");
        else element.style.removeProperty(property);
      });
    }
    window.addEventListener("resize", update);
    if (viewport) {
      viewport.addEventListener("resize", update);
      viewport.addEventListener("scroll", update);
    }
    update();
    return function () {
      window.removeEventListener("resize", update);
      if (viewport) {
        viewport.removeEventListener("resize", update);
        viewport.removeEventListener("scroll", update);
      }
      properties.forEach(function (name) {
        element.style.removeProperty("--ps-mobile-viewport-" + name);
      });
    };
  };

  core.uiImageUrl = function (url) {
    const images = (window.PLOTSRV_CONFIG || {}).ui_image_urls || {};
    return images[url] || url;
  };

  core.escapeHtml = function (s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  };

  core.findNearest = function (el, selector) {
    if (!el) return null;
    if (el.closest) return el.closest(selector);
    return null;
  };

  core.setStatusMessage = function (html) {
    const status = document.getElementById("status");
    if (status) status.innerHTML = html || "";
  };

  core.copyTextToClipboard = async function (text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // ignore
    }

    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "readonly");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return !!ok;
    } catch (e) {
      return false;
    }
  };
})();
