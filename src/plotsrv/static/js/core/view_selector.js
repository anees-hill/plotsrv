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
  const ICONS = {
    unknown: "/static/logo_unknown.png",
    plot: "/static/logo_plot.png",
    table: "/static/logo_table.png",
    stream: "/static/logo_stream.png",
    image: "/static/logo_image.png",
    markdown: "/static/logo_markdown.png",
    json: "/static/logo_json.png",
    observe: "/static/logo_observe.png",
    python: "/static/logo_python.png",
    traceback: "/static/logo_python_traceback.png",
    exception: "/static/logo_exception.png",
    text: "/static/logo_txt.png",
    html: "/static/logo_html.png",
  };
  if (core.uiImageUrl) {
    Object.keys(ICONS).forEach(key => { ICONS[key] = core.uiImageUrl(ICONS[key]); });
  }
  const CODE_LABELS = {python:"PY", r:"R", sql:"SQL", bash:"SH", javascript:"JS",
    typescript:"TS", css:"CSS", c:"C", cpp:"C++", go:"GO", rust:"RS"};

  function makeViewIcon(view, className) {
    let icon;
    if (view.icon_key === "code") {
      icon = element("span", className + " ps-code-view-icon");
      icon.setAttribute("aria-hidden", "true");
      icon.appendChild(element("span", "ps-code-view-icon__glyph"));
      icon.appendChild(element("span", "ps-code-view-icon__language",
        Object.prototype.hasOwnProperty.call(CODE_LABELS, view.code_language) ? CODE_LABELS[view.code_language] : "CODE"));
    } else {
      icon = element("img", className);
      icon.src = iconUrl(view);
      icon.alt = "";
    }
    icon.dataset.iconSignature = JSON.stringify([view.icon_key, view.code_language || ""]);
    return icon;
  }
  core.makeViewIcon = makeViewIcon;
  core.updateViewIcon = function (icon, view) {
    if (!icon || icon.dataset.iconSignature === JSON.stringify([view.icon_key, view.code_language || ""])) return;
    const className = icon.classList.contains("ps-viewselect__itemicon")
      ? "ps-viewselect__itemicon" : "ps-viewselect__icon";
    icon.replaceWith(makeViewIcon(view, className));
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
        code_language: cleanText(raw.code_language, "").toLowerCase(),
        description: typeof raw.description === "string" ? raw.description.slice(0, 512) : "",
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
      observe: "Observation",
      python: "Python object",
      code: "Code" + (view.code_language ? " · " + view.code_language : ""),
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
        caption: cleanText(raw.caption, view.description).slice(0, 512),
        thumbnail_url: safePresentationUrl(raw.thumbnail_url || raw.thumbnail),
      });
    }
    return resolved;
  }

  function resolveCompactViews(views, rawCompact) {
    const catalogue = normalizeViewCatalogue(views);
    const byId = new Map(catalogue.map(function (view) {
      return [view.view_id, view];
    }));
    const resolved = [];
    const seen = new Set();
    if (!Array.isArray(rawCompact)) return resolved;
    for (const raw of rawCompact) {
      const values = typeof raw === "string" ? {view_id: raw} : raw;
      if (!values || typeof values !== "object") continue;
      const viewId = cleanText(values.view_id || values.view, "");
      const view = byId.get(viewId);
      if (!view || seen.has(viewId)) continue;
      seen.add(viewId);
      resolved.push({
        view: view,
        title: cleanText(values.title, view.label),
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
    if (stored === "grouped" || stored === "az" || stored === "my") return stored;
    return "grouped";
  }

  function loadFeaturedDisplay() {
    const key = storageKey("featuredDisplay", "plotsrv:v1:featured_display");
    const stored = typeof core.loadPref === "function"
      ? core.loadPref(key, "expanded")
      : loadLocalPreference(key, "expanded");
    return stored === "compact" ? "compact" : "expanded";
  }

  function loadLocalPreference(key, fallback) {
    try {
      return localStorage.getItem(key) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function saveFeaturedDisplay(display) {
    const key = storageKey("featuredDisplay", "plotsrv:v1:featured_display");
    if (typeof core.savePref === "function") {
      core.savePref(key, display);
      return;
    }
    try {
      localStorage.setItem(key, display);
    } catch (e) {
      // Browser storage can be unavailable in private/restricted contexts.
    }
  }

  function pinnedStorageKey() {
    return storageKey("viewSelectorPinned", "plotsrv:v1:view_selector_pinned");
  }

  function loadPinnedViews(catalogue) {
    const valid = new Set(catalogue.map(function (view) { return view.view_id; }));
    try {
      const parsed = JSON.parse(localStorage.getItem(pinnedStorageKey()) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map(String)
        .filter(function (viewId, index, items) {
          return valid.has(viewId) && items.indexOf(viewId) === index;
        });
    } catch (e) {
      return [];
    }
  }

  function savePinnedViews(viewIds) {
    try {
      localStorage.setItem(pinnedStorageKey(), JSON.stringify(viewIds));
    } catch (e) {
      // ignore
    }
  }

  function togglePinnedView(viewId, catalogue) {
    const current = loadPinnedViews(catalogue);
    const existing = current.indexOf(viewId);
    if (existing >= 0) current.splice(existing, 1);
    else if (catalogue.some(function (view) { return view.view_id === viewId; })) {
      current.unshift(viewId);
    }
    savePinnedViews(current);
    return current;
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
    button.setAttribute("data-selected", selected ? "true" : "false");
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }

  function applyFreshness(button, view) {
    if (typeof core.applyViewFreshness === "function") {
      core.applyViewFreshness(button, view.freshness || null);
    }
  }

  function makePinButton(view, pinned) {
    const button = element(
      "button",
      "ps-viewselect__pin" + (pinned ? " ps-viewselect__pin--active" : ""),
      pinned ? "★" : "☆"
    );
    const action = pinned ? "Unpin" : "Pin";
    button.type = "button";
    button.setAttribute("data-pin-view", view.view_id);
    button.setAttribute("aria-pressed", pinned ? "true" : "false");
    button.setAttribute("aria-label", action + " " + view.label);
    button.title = action + " " + view.label;
    return button;
  }

  function wrapViewEntry(button, view, pinned, feature, compact) {
    const entry = element(
      "div",
      "ps-viewselect__entry" +
        (feature ? " ps-viewselect__entry--feature" : "") +
        (compact ? " ps-viewselect__entry--compact" : "")
    );
    entry.appendChild(button);
    entry.appendChild(makePinButton(view, pinned));
    entry.setAttribute("role", "listitem");
    return entry;
  }

  function makeViewItem(view, includeSection, pinned, compact) {
    const button = element(
      "button",
      "ps-viewselect__item" + (compact ? " ps-viewselect__item--compact" : "")
    );
    button.type = "button";
    button.setAttribute("data-plotsrv-view", view.view_id);
    button.setAttribute("data-view-section", view.section);
    button.setAttribute("data-view-kind", view.kind);
    button.setAttribute("data-view-icon", view.icon_key);
    applySelection(button, view);

    const freshness = element("span", "ps-viewselect__freshness");
    freshness.hidden = true;
    freshness.setAttribute("aria-hidden", "true");
    freshness.setAttribute("data-plotsrv-view-freshness", view.view_id);

    const copy = element("span", "ps-viewselect__itemcopy");
    copy.appendChild(
      element("span", "ps-viewselect__itemlabel", compact ? compact.title : view.label)
    );
    const meta = includeSection
      ? view.section + " · " + viewTypeLabel(view)
      : viewTypeLabel(view);
    copy.appendChild(element("span", "ps-viewselect__itemmeta", meta));
    if (view.description) copy.appendChild(element("span", "ps-viewselect__description", view.description));

    button.appendChild(freshness);
    if (!compact) {
      button.appendChild(makeViewIcon(view, "ps-viewselect__itemicon"));
    }
    button.appendChild(copy);
    const check = element("span", "ps-viewselect__check", "✓");
    check.setAttribute("aria-hidden", "true");
    button.appendChild(check);
    applyFreshness(button, view);
    return wrapViewEntry(button, view, pinned, false, !!compact);
  }

  function makeFeatureFallback(view) {
    const fallback = element("span", "ps-viewselect__feature-fallback");
    fallback.appendChild(makeViewIcon(view, "ps-viewselect__itemicon"));
    return fallback;
  }

  function makeFeatureItem(feature, pinned) {
    const view = feature.view;
    const button = element("button", "ps-viewselect__feature");
    button.type = "button";
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
    return wrapViewEntry(button, view, pinned, true, false);
  }

  function appendGroup(
    fragment,
    label,
    views,
    includeSection,
    pinnedIds,
    compactById
  ) {
    if (!views.length) return;
    const group = element("section", "ps-viewselect__group");
    group.setAttribute("aria-label", label);
    group.appendChild(element("h3", "ps-viewselect__group-label", label));
    const items = element("div", "ps-viewselect__group-items");
    items.setAttribute("role", "list");
    for (const view of views) {
      items.appendChild(
        makeViewItem(
          view,
          includeSection,
          pinnedIds.has(view.view_id),
          compactById ? compactById.get(view.view_id) : null
        )
      );
    }
    group.appendChild(items);
    fragment.appendChild(group);
  }

  function navigationEntries(catalogue, mode, features, pinnedIds, savedItems) {
    const known = new Map(catalogue.map(function (view) { return [view.view_id, view]; }));
    if (mode === "my") return (savedItems || []).filter(function (item) {
      return item && item.spec && known.has(item.spec.sourceId);
    }).map(function (item) { return {id: item.id, item: item}; });
    if (mode === "az") return catalogue.slice().sort(compareViews).map(function (view) {
      return {id: view.view_id, view: view};
    });
    const ordered = [];
    const seen = new Set();
    function push(view) {
      if (view && !seen.has(view.view_id)) {
        seen.add(view.view_id);
        ordered.push({id: view.view_id, view: view});
      }
    }
    const featuredIds = new Set(features.map(function (feature) { return feature.view.view_id; }));
    features.forEach(function (feature) { push(feature.view); });
    pinnedIds.forEach(function (id) { push(known.get(id)); });
    const groups = new Map();
    catalogue.forEach(function (view) {
      if (featuredIds.has(view.view_id)) return;
      if (!groups.has(view.section)) groups.set(view.section, []);
      groups.get(view.section).push(view);
    });
    groups.forEach(function (views) { views.forEach(push); });
    return ordered;
  }

  function createController(wrap) {
    const trigger = wrap.querySelector(".ps-viewselect__btn");
    const menu = wrap.querySelector(".ps-viewselect__menu");
    const search = wrap.querySelector(".ps-viewselect__search");
    const tabs = wrap.querySelector(".ps-viewselect__tabs");
    const layouts = wrap.querySelector(".ps-viewselect__layouts");
    const navigation = wrap.querySelector(".ps-viewselect__nav");
    const results = wrap.querySelector(".ps-viewselect__results");
    if (!trigger || !menu || !search || !tabs || !results) return null;

    const mobileHeader = element("div", "ps-viewselect__mobile-header");
    mobileHeader.appendChild(element("strong", "", "Views"));
    const close = element("button", "ps-viewselect__close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close view picker");
    mobileHeader.appendChild(close);
    menu.prepend(mobileHeader);
    let stopTrackingViewport = null;

    const controller = {
      catalogue: normalizeViewCatalogue(config.viewCatalogue),
      mode: "grouped",
      layout: core.loadPref && core.loadPref(core.storageKeys.viewSelectorLayout, "standard") === "compact" ? "compact" : "standard",
      query: "",
      pinned: [],
      featuredDisplay: loadFeaturedDisplay(),
      renderFrame: null,
    };
    controller.mode = initialViewSelectorMode();
    controller.pinned = loadPinnedViews(controller.catalogue);
    savePinnedViews(controller.pinned);

    function availableFeatures() {
      return resolveFeaturedViews(controller.catalogue, config.featuredViews);
    }

    function currentNavigationEntries() {
      const saved = controller.mode === "my" && core.viewSpec ? core.viewSpec.read().items : [];
      return navigationEntries(controller.catalogue, controller.mode, availableFeatures(), controller.pinned, saved);
    }

    function syncNavigation() {
      if (!navigation) return;
      wrap.setAttribute("data-nav-hidden", core.viewNavigationEnabled && !core.viewNavigationEnabled() ? "true" : "false");
      const entries = currentNavigationEntries();
      const personalId = new URL(window.location.href).searchParams.get("my_view");
      const selectedId = controller.mode === "my" ? personalId : config.activeViewId;
      const canStep = entries.length > 0 && (entries.length > 1 || entries[0].id !== selectedId);
      navigation.querySelectorAll("button").forEach(function (button) { button.disabled = !canStep; });
    }

    function stepView(direction) {
      const entries = currentNavigationEntries();
      if (!entries.length) return;
      const personalId = new URL(window.location.href).searchParams.get("my_view");
      const selectedId = controller.mode === "my" ? personalId : config.activeViewId;
      const index = entries.findIndex(function (entry) { return entry.id === selectedId; });
      const next = entries[index < 0 ? (direction > 0 ? 0 : entries.length - 1)
        : (index + direction + entries.length) % entries.length];
      if (!next || next.id === selectedId) return;
      saveScrollTop();
      window.location.href = next.item ? core.personalViewUrl(next.item)
        : window.location.pathname + "?view=" + encodeURIComponent(next.id);
    }

    function renderTabs() {
      const modes = [["grouped", "Grouped"], ["az", "A–Z"], ["my", "My views"]];
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

    function arrangeCompactColumns(fragment) {
      const groups = Array.from(fragment.children);
      const sizes = groups.map(function (group) {
        const list = group.querySelector("[role='list']");
        return list ? list.children.length : 0;
      });
      const count = sizes.reduce(function (sum, size) { return sum + size; }, 0);
      if (!count) return;
      const columns = [element("div", "ps-viewselect__column"), element("div", "ps-viewselect__column")];
      let leftTarget = Math.ceil(count / 2);
      if (!sizes.some(function (size) { return size > leftTarget; })) {
        let prefix = 0;
        let bestGap = Infinity;
        for (let index = 0; index < sizes.length - 1; index++) {
          prefix += sizes[index];
          const gap = Math.abs(count - 2 * prefix);
          if (gap < bestGap) { bestGap = gap; leftTarget = prefix; }
        }
      }
      let leftCount = 0;
      for (const group of groups) {
        const list = group.querySelector("[role='list']");
        if (!list) { columns[leftCount < leftTarget ? 0 : 1].appendChild(group); continue; }
        const rows = Array.from(list.children);
        const leftTake = Math.max(0, Math.min(rows.length, leftTarget - leftCount));
        if (leftTake === 0) { columns[1].appendChild(group); continue; }
        columns[0].appendChild(group);
        leftCount += leftTake;
        if (leftTake < rows.length) {
          const continuation = group.cloneNode(false);
          const heading = group.querySelector(".ps-viewselect__group-label");
          if (heading) continuation.appendChild(heading.cloneNode(true));
          const remainder = list.cloneNode(false);
          rows.slice(leftTake).forEach(function (row) { remainder.appendChild(row); });
          continuation.appendChild(remainder);
          columns[1].appendChild(continuation);
        }
      }
      fragment.replaceChildren.apply(fragment, columns);
    }

    function scrollStorageKey() {
      return "plotsrv:v1:view_selector_scroll:" + controller.mode + ":" + controller.layout;
    }

    function savedScrollTop() {
      try {
        const value = Number(sessionStorage.getItem(scrollStorageKey()));
        return Number.isFinite(value) && value > 0 ? value : 0;
      } catch (e) {
        return 0;
      }
    }

    function saveScrollTop() {
      if (controller.query || menu.hidden) return;
      try {
        sessionStorage.setItem(scrollStorageKey(), String(results.scrollTop));
      } catch (e) {
        // Session storage can be unavailable in restricted browsers.
      }
    }

    function render() {
      controller.renderFrame = null;
      const features = availableFeatures();
      const featuredIds = new Set(features.map(function (feature) {
        return feature.view.view_id;
      }));
      const compactById = new Map(
        resolveCompactViews(controller.catalogue, config.compactViews)
          .filter(function (item) { return !featuredIds.has(item.view.view_id); })
          .map(function (item) { return [item.view.view_id, item]; })
      );
      renderTabs();
      syncNavigation();
      if (layouts) layouts.querySelectorAll("[data-view-layout]").forEach(function (button) {
        button.setAttribute("aria-pressed", button.getAttribute("data-view-layout") === controller.layout ? "true" : "false");
      });
      menu.classList.toggle("ps-viewselect__menu--compact", controller.layout === "compact");
      results.classList.toggle("ps-viewselect__results--compact", controller.layout === "compact");
      const fragment = document.createDocumentFragment();
      const query = controller.query.trim();
      const pinnedIds = new Set(controller.pinned);

      if (controller.mode === "my") {
        const loaded = core.viewSpec ? core.viewSpec.read() : {items:[], error:null};
        const matching = loaded.items.filter(item => (item.spec.name + " " + item.spec.caption + " " + item.spec.sourceId).toLowerCase().includes(query.toLowerCase()));
        const known = new Map(controller.catalogue.map(view => [view.view_id, view]));
        if (loaded.error || !matching.length) fragment.appendChild(element("p", "ps-viewselect__empty", loaded.error || (query ? "No matching saved views." : "Change table or plot settings, then choose Save view to save a presentation on this browser. Ordinary sources remain in Grouped and A–Z.")));
        matching.forEach(item => {
          const row = element("div", "ps-viewselect__entry");
          const open = element("button", "ps-viewselect__item"); open.type = "button";
          open.setAttribute("data-plotsrv-view", item.spec.sourceId); open.setAttribute("data-personal-view", item.id);
          const current = new URL(window.location.href).searchParams.get("my_view") === item.id;
          open.setAttribute("data-selected", current ? "true" : "false");
          if (current) open.setAttribute("aria-current", "page");
          open.disabled = !known.has(item.spec.sourceId);
          open.appendChild(makeViewIcon(known.get(item.spec.sourceId) || {icon_key: "unknown"}, "ps-viewselect__itemicon"));
          const copy = element("span", "ps-viewselect__itemcopy");
          copy.appendChild(element("span", "ps-viewselect__itemlabel", item.spec.name));
          copy.appendChild(element("span", "ps-viewselect__itemmeta", (known.has(item.spec.sourceId) ? item.spec.caption || known.get(item.spec.sourceId).description || item.spec.sourceId : "Source unavailable — " + item.spec.sourceId)));
          open.appendChild(copy);
          const check = element("span", "ps-viewselect__check", "✓"); check.setAttribute("aria-hidden", "true"); open.appendChild(check);
          row.appendChild(open);
          const remove = element("button", "ps-viewselect__delete", "×"); remove.type = "button";
          remove.setAttribute("data-personal-delete", item.id); remove.setAttribute("aria-label", "Delete saved view " + item.spec.name);
          row.appendChild(remove); fragment.appendChild(row);
        });
      } else if (query) {
        appendGroup(
          fragment,
          "Search results",
          filterViewCatalogue(controller.catalogue, query).sort(compareViews),
          true,
          pinnedIds,
          compactById
        );
      } else if (controller.mode === "az") {
        appendGroup(
          fragment,
          "All views",
          controller.catalogue.slice().sort(compareViews),
          true,
          pinnedIds,
          compactById
        );
      } else {
        if (features.length) {
          const featuredGroup = element(
            "section",
            "ps-viewselect__group ps-viewselect__group--featured"
          );
          featuredGroup.setAttribute("aria-label", "Featured");
          const heading = element("div", "ps-viewselect__group-heading");
          heading.appendChild(element("h3", "ps-viewselect__group-label", "Featured"));
          const toggle = element(
            "button",
            "ps-viewselect__featured-toggle",
            controller.featuredDisplay === "compact" ? "Show cards" : "Show as list"
          );
          toggle.type = "button";
          toggle.setAttribute("data-featured-display-toggle", "");
          toggle.setAttribute("aria-label", controller.featuredDisplay === "compact"
            ? "Show featured views as cards" : "Show featured views as a list");
          heading.appendChild(toggle);
          featuredGroup.appendChild(heading);
          const compact = controller.featuredDisplay === "compact";
          const featureList = element("div", compact
            ? "ps-viewselect__group-items" : "ps-viewselect__features");
          featureList.setAttribute("role", "list");
          for (const feature of features) {
            featureList.appendChild(
              compact
                ? makeViewItem(feature.view, false, pinnedIds.has(feature.view.view_id), null)
                : makeFeatureItem(feature, pinnedIds.has(feature.view.view_id))
            );
          }
          featuredGroup.appendChild(featureList);
          fragment.appendChild(featuredGroup);
        }

        const byId = new Map(controller.catalogue.map(function (view) {
          return [view.view_id, view];
        }));
        const pinned = controller.pinned
          .map(function (viewId) { return byId.get(viewId); })
          .filter(Boolean);
        appendGroup(fragment, "Pinned views", pinned, true, pinnedIds, compactById);

        const groups = new Map();
        for (const view of controller.catalogue) {
          if (featuredIds.has(view.view_id)) continue;
          if (!groups.has(view.section)) groups.set(view.section, []);
          groups.get(view.section).push(view);
        }
        groups.forEach(function (views, section) {
          appendGroup(fragment, section, views, false, pinnedIds, compactById);
        });
      }

      if (controller.layout === "compact" && controller.mode === "my") {
        const group = element("section", "ps-viewselect__group");
        group.setAttribute("aria-label", "My views");
        group.appendChild(element("h3", "ps-viewselect__group-label", "My views"));
        const list = element("div", "ps-viewselect__group-items");
        list.setAttribute("role", "list");
        Array.from(fragment.querySelectorAll(".ps-viewselect__entry")).forEach(function (row) { list.appendChild(row); });
        if (list.children.length) { group.appendChild(list); fragment.replaceChildren(group); }
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
      if (controller.layout === "compact") arrangeCompactColumns(fragment);
      results.replaceChildren(fragment);
      results.scrollTop = query ? 0 : savedScrollTop();
      const items = Array.from(results.querySelectorAll("[data-plotsrv-view]"));
      const roving = items.find(function (item) {
        return item.getAttribute("aria-current") === "page";
      }) || items[0];
      items.forEach(function (item) { item.tabIndex = item === roving ? 0 : -1; });
    }

    function scheduleRender() {
      if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
      controller.renderFrame = requestAnimationFrame(render);
    }

    function setMode(mode, focusTab) {
      if (mode !== "grouped" && mode !== "az" && mode !== "my") return;
      saveScrollTop();
      controller.mode = mode;
      saveViewSelectorMode(mode);
      render();
      if (focusTab) {
        const selectedTab = tabs.querySelector('[data-view-mode="' + mode + '"]');
        if (selectedTab) selectedTab.focus();
      }
    }

    function clampMenuToViewport() {
      if (window.matchMedia("(max-width: 640px)").matches) {
        // Mobile uses both viewport edges; a one-sided clamp can let the
        // content's intrinsic width stretch the panel past the screen.
        menu.style.left = "";
        menu.style.right = "";
        return;
      }
      const fixed = window.getComputedStyle(menu).position === "fixed";
      menu.style.left = "";
      menu.style.right = fixed ? "" : "0";
      const rect = menu.getBoundingClientRect();
      const pad = 8;
      const desiredLeft = Math.max(pad, Math.min(rect.left, window.innerWidth - pad - rect.width));
      menu.style.right = "auto";
      const origin = fixed ? 0 : wrap.getBoundingClientRect().left;
      menu.style.left = (desiredLeft - origin) + "px";
    }

    function openMenu() {
      menu.hidden = false;
      if (stopTrackingViewport) stopTrackingViewport();
      if (core.trackMobileViewport) stopTrackingViewport = core.trackMobileViewport(menu);
      trigger.setAttribute("aria-expanded", "true");
      render();
      requestAnimationFrame(function () {
        if (menu.hidden) return;
        clampMenuToViewport();
        if (window.matchMedia("(max-width: 640px)").matches) close.focus({ preventScroll: true });
        else search.focus();
      });
    }

    function closeMenu(restoreFocus) {
      if (menu.hidden) return;
      menu.hidden = true;
      if (stopTrackingViewport) stopTrackingViewport();
      stopTrackingViewport = null;
      trigger.setAttribute("aria-expanded", "false");
      if (controller.query) {
        controller.query = "";
        search.value = "";
        render();
      }
      if (restoreFocus) trigger.focus({ preventScroll: true });
    }

    close.addEventListener("click", function () { closeMenu(true); });

    controller.setCatalogue = function (views) {
      controller.catalogue = normalizeViewCatalogue(views);
      config.viewCatalogue = controller.catalogue;
      if (core.syncViewExplanation) core.syncViewExplanation();
      controller.pinned = loadPinnedViews(controller.catalogue);
      savePinnedViews(controller.pinned);
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
    if (navigation) navigation.addEventListener("click", function (event) {
      const button = event.target.closest && event.target.closest("[data-view-step]");
      if (button && !button.disabled) stepView(Number(button.getAttribute("data-view-step")));
    });
    window.addEventListener("plotsrv:viewnavigationchange", syncNavigation);
    search.addEventListener("input", function () {
      controller.query = search.value;
      scheduleRender();
    });
    results.addEventListener("scroll", saveScrollTop);
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
    if (layouts) layouts.addEventListener("click", function (event) {
      const button = event.target.closest && event.target.closest("[data-view-layout]");
      if (!button) return;
      saveScrollTop();
      controller.layout = button.getAttribute("data-view-layout") === "compact" ? "compact" : "standard";
      core.savePref(core.storageKeys.viewSelectorLayout, controller.layout);
      render();
      clampMenuToViewport();
      layouts.querySelector('[data-view-layout="' + controller.layout + '"]').focus();
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
    window.addEventListener("plotsrv-my-views-changed", scheduleRender);
    results.addEventListener("click", async function (event) {
      const displayToggle = event.target.closest && event.target.closest("[data-featured-display-toggle]");
      if (displayToggle) {
        event.preventDefault();
        controller.featuredDisplay = controller.featuredDisplay === "compact" ? "expanded" : "compact";
        saveFeaturedDisplay(controller.featuredDisplay);
        render();
        results.querySelector("[data-featured-display-toggle]").focus();
        return;
      }
      const personal = event.target.closest && event.target.closest("[data-personal-view], [data-personal-delete]");
      if (personal) {
        event.preventDefault(); event.stopPropagation();
        const deleting = personal.hasAttribute("data-personal-delete");
        const id = personal.getAttribute(deleting ? "data-personal-delete" : "data-personal-view");
        const item = core.viewSpec.read().items.find(value => value.id === id);
        if (!item) { render(); return; }
        if (deleting) {
          if (await core.deletePersonalView(item)) {
            if (controller.renderFrame !== null) cancelAnimationFrame(controller.renderFrame);
            render();
            const next = results.querySelector("[data-personal-delete]") || search;
            if (next) next.focus();
          }
        } else window.location.href = core.personalViewUrl(item);
        return;
      }
      const pin = event.target.closest && event.target.closest("[data-pin-view]");
      if (pin) {
        event.preventDefault();
        event.stopPropagation();
        const pinnedViewId = pin.getAttribute("data-pin-view");
        controller.pinned = togglePinnedView(
          pinnedViewId,
          controller.catalogue
        );
        render();
        const pinButtons = Array.from(results.querySelectorAll("[data-pin-view]"));
        const nextPin = pinButtons.find(function (button) {
          return button.getAttribute("data-pin-view") === pinnedViewId;
        });
        if (nextPin) nextPin.focus();
        return;
      }
      const item = event.target.closest && event.target.closest("[data-plotsrv-view]");
      if (!item) return;
      const viewId = item.getAttribute("data-plotsrv-view");
      if (!viewId) return;
      saveScrollTop();
      window.location.href = window.location.pathname + "?view=" + encodeURIComponent(viewId);
    });
    // Escape can arrive while focus is still on the trigger, before the
    // opening animation frame moves it into the menu. Handle both locations.
    wrap.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !menu.hidden) {
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
    else if (core.syncViewExplanation) core.syncViewExplanation();
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
  core.resolveCompactViews = resolveCompactViews;
  core.initialViewSelectorMode = initialViewSelectorMode;
  core.saveViewSelectorMode = saveViewSelectorMode;
  core.loadPinnedViews = loadPinnedViews;
  core.togglePinnedView = togglePinnedView;
  core.updateViewSelectorCatalogue = updateViewSelectorCatalogue;
  core.bindViewDropdown = bindViewDropdown;
})();
