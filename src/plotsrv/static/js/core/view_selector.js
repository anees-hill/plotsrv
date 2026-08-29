(function () {
  "use strict";

  window.PLOTSRV = window.PLOTSRV || {
    core: {},
    renderers: {},
    state: {},
    config: {},
  };

  const core = window.PLOTSRV.core;
  const config = window.PLOTSRV.config;
  const MAX_RECENT_VIEWS = 4;
  const ICONS = {
    unknown: "/static/logo_unknown.png",
    plot: "/static/logo_plot.png",
    table: "/static/logo_table.png",
    image: "/static/logo_image.png",
    markdown: "/static/logo_markdown.png",
    json: "/static/logo_json.png",
    python: "/static/logo_python.png",
    traceback: "/static/logo_exception.png",
    exception: "/static/logo_exception.png",
    text: "/static/logo_txt.png",
    html: "/static/logo_html.png",
  };
  let activeController = null;

  function cleanText(value, fallback) {
    if (value === null || value === undefined) return fallback || "";
    return String(value).trim() || fallback || "";
  }

  function normalizeViewCatalogue(rawViews) {
    if (!Array.isArray(rawViews)) return [];
    const seen = new Set();
    const views = [];
    for (const raw of rawViews) {
      if (!raw || typeof raw !== "object") continue;
      const viewId = cleanText(raw.view_id, "");
      if (!viewId || seen.has(viewId)) continue;
      seen.add(viewId);
      views.push({
        view_id: viewId,
        label: cleanText(raw.label, viewId),
        section: cleanText(raw.section, "default"),
        kind: cleanText(raw.kind, "none").toLowerCase(),
        icon_key: cleanText(raw.icon_key, "unknown").toLowerCase(),
        freshness:
          raw.freshness && typeof raw.freshness === "object"
            ? raw.freshness
            : null,
      });
    }
    return views;
  }

  function compareViews(a, b) {
    return (
      a.label.localeCompare(b.label, undefined, {
        sensitivity: "base",
        numeric: true,
      }) ||
      a.section.localeCompare(b.section, undefined, { sensitivity: "base" }) ||
      a.view_id.localeCompare(b.view_id, undefined, { sensitivity: "base" })
    );
  }

  function sortViewsAlphabetically(views) {
    return normalizeViewCatalogue(views).slice().sort(compareViews);
  }

  function viewTypeLabel(view) {
    const labels = {
      plot: "Plot",
      table: "Table",
      stream: "Live stream",
      image: "Image",
      markdown: "Markdown",
      json: "JSON",
      python: "Python object",
      traceback: "Traceback",
      exception: "Exception",
      text: "Text",
      html: "HTML",
    };
    return labels[view.icon_key] || labels[view.kind] || "View";
  }

  function filterViewCatalogue(views, query) {
    const words = cleanText(query, "")
      .toLocaleLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const catalogue = normalizeViewCatalogue(views);
    if (!words.length) return catalogue;
    return catalogue.filter(function (view) {
      const haystack = [
        view.label,
        view.view_id,
        view.section,
        view.kind,
        view.icon_key,
        viewTypeLabel(view),
      ]
        .join(" ")
        .toLocaleLowerCase();
      return words.every(function (word) {
        return haystack.includes(word);
      });
    });
  }

  function safePresentationUrl(value) {
    const url = cleanText(value, "");
    if (!url) return "";
    const scheme = url.match(/^([a-z][a-z0-9+.-]*):/i);
    if (scheme && !/^https?:$/i.test(scheme[0])) return "";
    return url;
  }

  function resolveFeaturedViews(views, rawFeatures) {
    const catalogue = normalizeViewCatalogue(views);
    const byId = new Map(
      catalogue.map(function (view) {
        return [view.view_id, view];
      })
    );
    const seen = new Set();
    const resolved = [];
    if (!Array.isArray(rawFeatures)) return resolved;
    for (const raw of rawFeatures) {
      if (!raw || typeof raw !== "object") continue;
      const viewId = cleanText(raw.view_id || raw.view, "");
      const view = byId.get(viewId);
      if (!view || seen.has(viewId)) continue;
      seen.add(viewId);
      resolved.push({
        view: view,
        title: cleanText(raw.title, view.label),
        caption: cleanText(raw.caption, ""),
        thumbnail_url: safePresentationUrl(raw.thumbnail_url || raw.thumbnail),
      });
    }
    return resolved;
  }

  function storageKey(name, fallback) {
    return core.storageKeys && core.storageKeys[name]
      ? core.storageKeys[name]
      : fallback;
  }

  function loadStoredMode() {
    const key = storageKey("viewSelectorMode", "plotsrv:v1:view_selector_mode");
    if (typeof core.loadPref === "function") return core.loadPref(key, null);
    try {
      return localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function saveViewSelectorMode(mode) {
    const key = storageKey("viewSelectorMode", "plotsrv:v1:view_selector_mode");
    if (typeof core.savePref === "function") {
      core.savePref(key, mode);
      return;
    }
    try {
      localStorage.setItem(key, String(mode));
    } catch (e) {
      // Browser storage can be unavailable in private/restricted contexts.
    }
  }

  function initialViewSelectorMode() {
    const stored = loadStoredMode();
    if (stored === "grouped" || stored === "az") return stored;
    return "grouped";
  }

  function recentStorageKey() {
    return storageKey("viewSelectorRecent", "plotsrv:v1:view_selector_recent");
  }

  function loadRecentViews(catalogue) {
    const valid = new Set(catalogue.map(function (view) { return view.view_id; }));
    try {
      const parsed = JSON.parse(localStorage.getItem(recentStorageKey()) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(String)
        .filter(function (viewId, index, items) {
          return valid.has(viewId) && items.indexOf(viewId) === index;
        })
        .slice(0, MAX_RECENT_VIEWS);
    } catch (e) {
      return [];
    }
  }

  function saveRecentViews(viewIds) {
    try {
      localStorage.setItem(
        recentStorageKey(),
        JSON.stringify(viewIds.slice(0, MAX_RECENT_VIEWS))
      );
    } catch (e) {
      // ignore
    }
  }

  function rememberRecentView(viewId, catalogue) {
    if (!viewId) return [];
    const recent = loadRecentViews(catalogue).filter(function (item) {
      return item !== viewId;
    });
    if (catalogue.some(function (view) { return view.view_id === viewId; })) {
      recent.unshift(viewId);
    }
    const bounded = recent.slice(0, MAX_RECENT_VIEWS);
    saveRecentViews(bounded);
    return bounded;
  }

  function iconUrl(view) {
    return ICONS[view.icon_key] || ICONS.unknown;
  }

  function element(tagName, className, textValue) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (textValue !== undefined) node.textContent = textValue;
    return node;
  }

  function applySelection(button, view) {
    const selected = view.view_id === config.activeViewId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }

  function applyFreshness(button, view) {
    if (typeof core.applyViewFreshness === "function") {
      core.applyViewFreshness(button, view.freshness || null);
    }
  }

  function makeViewItem(view, includeSection) {
    const button = element("button", "ps-viewselect__item");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("data-plotsrv-view", view.view_id);
    button.setAttribute("data-view-section", view.section);
    button.setAttribute("data-view-kind", view.kind);
    button.setAttribute("data-view-icon", view.icon_key);
    applySelection(button, view);

    const freshness = element("span", "ps-viewselect__freshness");
    freshness.hidden = true;
    freshness.setAttribute("aria-hidden", "true");
    freshness.setAttribute("data-plotsrv-view-freshness", view.view_id);

    const image = element("img", "ps-viewselect__itemicon");
    image.src = iconUrl(view);
    image.alt = "";

    const copy = element("span", "ps-viewselect__itemcopy");
    copy.appendChild(element("span", "ps-viewselect__itemlabel", view.label));
    const meta = includeSection
      ? view.section + " · " + viewTypeLabel(view)
      : viewTypeLabel(view);
    copy.appendChild(element("span", "ps-viewselect__itemmeta", meta));

    button.appendChild(freshness);
    button.appendChild(image);
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return button;
  }

  function makeFeatureFallback(view) {
    const fallback = element("span", "ps-viewselect__feature-fallback");
    const image = element("img");
    image.src = iconUrl(view);
    image.alt = "";
    fallback.appendChild(image);
    return fallback;
  }

  function makeFeatureItem(feature) {
    const view = feature.view;
    const button = element("button", "ps-viewselect__feature");
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("data-plotsrv-view", view.view_id);
    applySelection(button, view);

    let visual;
    if (feature.thumbnail_url) {
      visual = element("img", "ps-viewselect__feature-thumbnail");
      visual.src = feature.thumbnail_url;
      visual.alt = "";
      visual.loading = "lazy";
      visual.addEventListener(
        "error",
        function () {
          const fallback = makeFeatureFallback(view);
          if (visual.parentNode) visual.parentNode.replaceChild(fallback, visual);
        },
        { once: true }
      );
    } else {
      visual = makeFeatureFallback(view);
    }

    const copy = element("span", "ps-viewselect__feature-copy");
    copy.appendChild(element("span", "ps-viewselect__feature-title", feature.title));
    if (feature.caption) {
      copy.appendChild(
        element("span", "ps-viewselect__feature-caption", feature.caption)
      );
    }
    copy.appendChild(
      element("span", "ps-viewselect__feature-kind", viewTypeLabel(view))
    );

    button.appendChild(visual);
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return button;
  }

  function appendGroup(fragment, label, views, includeSection) {
    if (!views.length) return;
    const group = element("section", "ps-viewselect__group");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", label);
    group.appendChild(element("h3", "ps-viewselect__group-label", label));
    const items = element("div", "ps-viewselect__group-items");
    for (const view of views) items.appendChild(makeViewItem(view, includeSection));
    group.appendChild(items);
    fragment.appendChild(group);
  }

  function createController(wrap) {
    const trigger = wrap.querySelector(".ps-viewselect__btn");
    const menu = wrap.querySelector(".ps-viewselect__menu");
    const search = wrap.querySelector(".ps-viewselect__search");
    const tabs = wrap.querySelector(".ps-viewselect__tabs");
    const results = wrap.querySelector(".ps-viewselect__results");
    if (!trigger || !menu || !search || !tabs || !results) return null;

    const controller = {
      catalogue: normalizeViewCatalogue(config.viewCatalogue),
      mode: "grouped",
      query: "",
      recent: [],
      renderFrame: null,
    };
    controller.mode = initialViewSelectorMode();
    controller.recent = rememberRecentView(
      config.activeViewId,
      controller.catalogue
    );

    function availableFeatures() {
      return resolveFeaturedViews(controller.catalogue, config.featuredViews);
    }

    function renderTabs() {
      const modes = [["grouped", "Grouped"], ["az", "A–Z"]];
      const nodes = modes.map(function (entry) {
        const tab = element("button", "ps-viewselect__tab", entry[1]);
        const selected = entry[0] === controller.mode;
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.setAttribute("data-view-mode", entry[0]);
        tab.setAttribute("aria-controls", "view-selector-results");
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        return tab;
      });
      tabs.replaceChildren.apply(tabs, nodes);
    }

    function render() {
      controller.renderFrame = null;
      const features = availableFeatures();
      renderTabs();
      const fragment = document.createDocumentFragment();
      const query = controller.query.trim();

      if (query) {
        appendGroup(
          fragment,
          "Search results",
          filterViewCatalogue(controller.catalogue, query).sort(compareViews),
          true
        );
      } else if (controller.mode === "az") {
        appendGroup(
          fragment,
          "All views",
          controller.catalogue.slice().sort(compareViews),
          true
        );
      } else {
        const featuredIds = new Set(features.map(function (feature) {
          return feature.view.view_id;
        }));
        if (features.length) {
          const featuredGroup = element(
            "section",
            "ps-viewselect__group ps-viewselect__group--featured"
          );
          featuredGroup.setAttribute("role", "group");
          featuredGroup.setAttribute("aria-label", "Featured");
          featuredGroup.appendChild(
            element("h3", "ps-viewselect__group-label", "Featured")
          );
          const featureList = element("div", "ps-viewselect__features");
          for (const feature of features) {
            featureList.appendChild(makeFeatureItem(feature));
          }
          featuredGroup.appendChild(featureList);
          fragment.appendChild(featuredGroup);
        }

        const byId = new Map(controller.catalogue.map(function (view) {
          return [view.view_id, view];
        }));
        const recent = controller.recent
          .map(function (viewId) { return byId.get(viewId); })
          .filter(function (view) {
            return view && !featuredIds.has(view.view_id);
          });
        appendGroup(fragment, "Recent", recent, true);

        const groups = new Map();
        for (const view of controller.catalogue) {
          if (featuredIds.has(view.view_id)) continue;
          if (!groups.has(view.section)) groups.set(view.section, []);
          groups.get(view.section).push(view);
        }
        groups.forEach(function (views, section) {
          appendGroup(fragment, section, views, false);
        });
      }

      if (!fragment.childNodes.length) {
        const empty = element(
          "div",
          "ps-viewselect__empty",
          query ? "No views match your search." : "No views are available."
        );
        empty.setAttribute("role", "status");
        fragment.appendChild(empty);
      }
      results.replaceChildren(fragment);
      const items = Array.from(results.querySelectorAll("[data-plotsrv-view]"));
      const roving = items.find(function (item) {
        return item.getAttribute("aria-selected") === "true";
      }) || items[0];
      items.forEach(function (item) { item.tabIndex = item === roving ? 0 : -1; });
    }

    function scheduleRender() {
      if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
      controller.renderFrame = requestAnimationFrame(render);
    }

    function setMode(mode, focusTab) {
      if (mode !== "grouped" && mode !== "az") return;
      controller.mode = mode;
      saveViewSelectorMode(mode);
      render();
      if (focusTab) {
        const selectedTab = tabs.querySelector('[data-view-mode="' + mode + '"]');
        if (selectedTab) selectedTab.focus();
      }
    }

    function clampMenuToViewport() {
      menu.classList.remove("ps-viewselect__menu--clamped-left");
      menu.classList.remove("ps-viewselect__menu--clamped-right");
      const rect = menu.getBoundingClientRect();
      const pad = 8;
      if (rect.left < pad) menu.classList.add("ps-viewselect__menu--clamped-left");
      if (rect.right > window.innerWidth - pad) {
        menu.classList.add("ps-viewselect__menu--clamped-right");
      }
    }

    function openMenu() {
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      render();
      requestAnimationFrame(function () {
        clampMenuToViewport();
        search.focus();
      });
    }

    function closeMenu(restoreFocus) {
      if (menu.hidden) return;
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (controller.query) {
        controller.query = "";
        search.value = "";
        render();
      }
      if (restoreFocus) trigger.focus();
    }

    controller.setCatalogue = function (views) {
      controller.catalogue = normalizeViewCatalogue(views);
      config.viewCatalogue = controller.catalogue;
      controller.recent = loadRecentViews(controller.catalogue);
      render();
    };

    trigger.addEventListener("click", function () {
      if (menu.hidden) openMenu();
      else closeMenu(false);
    });
    trigger.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (menu.hidden) openMenu();
        else search.focus();
      }
    });
    search.addEventListener("input", function () {
      controller.query = search.value;
      scheduleRender();
    });
    search.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown") return;
      const first = results.querySelector("[data-plotsrv-view]");
      if (first) {
        event.preventDefault();
        first.focus();
      }
    });
    tabs.addEventListener("click", function (event) {
      const tab = event.target.closest && event.target.closest("[data-view-mode]");
      if (tab) {
        event.stopPropagation();
        setMode(tab.getAttribute("data-view-mode"), true);
      }
    });
    tabs.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const allTabs = Array.from(tabs.querySelectorAll("[data-view-mode]"));
      const index = allTabs.indexOf(event.target);
      if (index < 0) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = allTabs[(index + offset + allTabs.length) % allTabs.length];
      setMode(next.getAttribute("data-view-mode"), true);
    });
    results.addEventListener("keydown", function (event) {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const items = Array.from(results.querySelectorAll("[data-plotsrv-view]"));
      if (!items.length) return;
      let index = items.indexOf(event.target.closest("[data-plotsrv-view]"));
      if (event.key === "Home") index = 0;
      else if (event.key === "End") index = items.length - 1;
      else if (event.key === "ArrowDown") index = Math.min(items.length - 1, index + 1);
      else index = Math.max(0, index - 1);
      event.preventDefault();
      items.forEach(function (item, itemIndex) {
        item.tabIndex = itemIndex === index ? 0 : -1;
      });
      items[index].focus();
    });
    results.addEventListener("click", function (event) {
      const item = event.target.closest && event.target.closest("[data-plotsrv-view]");
      if (!item) return;
      const viewId = item.getAttribute("data-plotsrv-view");
      if (!viewId) return;
      controller.recent = rememberRecentView(viewId, controller.catalogue);
      window.location.href = "/?view=" + encodeURIComponent(viewId);
    });
    menu.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu(true);
      }
    });
    document.addEventListener("click", function (event) {
      const path = typeof event.composedPath === "function"
        ? event.composedPath()
        : [];
      const cameFromSelector = path.length
        ? path.includes(wrap)
        : wrap.contains(event.target);
      if (!cameFromSelector) closeMenu(false);
    });
    window.addEventListener("resize", function () {
      if (!menu.hidden) clampMenuToViewport();
    });

    render();
    return controller;
  }

  function updateViewSelectorCatalogue(views) {
    config.viewCatalogue = normalizeViewCatalogue(views);
    if (activeController) activeController.setCatalogue(config.viewCatalogue);
  }

  function bindViewDropdown() {
    const wrap = document.querySelector("[data-plotsrv-viewselect='1']");
    if (wrap) {
      if (wrap.getAttribute("data-view-selector-bound") === "true") return;
      wrap.setAttribute("data-view-selector-bound", "true");
      activeController = createController(wrap);
      return;
    }

    const select = document.getElementById("view-select");
    if (!select) return;
    select.addEventListener("change", function () {
      window.location.href = "/?view=" + encodeURIComponent(select.value);
    });
  }

  core.viewSelectorIcons = ICONS;
  core.normalizeViewCatalogue = normalizeViewCatalogue;
  core.sortViewsAlphabetically = sortViewsAlphabetically;
  core.filterViewCatalogue = filterViewCatalogue;
  core.resolveFeaturedViews = resolveFeaturedViews;
  core.initialViewSelectorMode = initialViewSelectorMode;
  core.saveViewSelectorMode = saveViewSelectorMode;
  core.updateViewSelectorCatalogue = updateViewSelectorCatalogue;
  core.bindViewDropdown = bindViewDropdown;
})();
