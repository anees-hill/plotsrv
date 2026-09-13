(function () {
  "use strict";

  const app = window.PLOTSRV;
  const core = app.core;
  let preference = { view: null, open: false, depth: 3 };
  let serial = 0;
  let dispose = null;
  let copying = false;

  function initCodeCopies(markdown) {
    const blocks = [];
    const walker = document.createTreeWalker(markdown, NodeFilter.SHOW_ELEMENT);
    let node;
    let visited = 0;
    while (visited++ < 10000 && blocks.length < 1000 && (node = walker.nextNode())) {
      if (node.tagName === "PRE" && node.firstElementChild && node.firstElementChild.tagName === "CODE") {
        blocks.push(node);
      }
    }
    const buttons = new Map();
    const wrappers = [];
    let active = true;
    let feedbackButton = null;
    let timer = 0;
    blocks.forEach(pre => {
      const wrapper = document.createElement("div");
      wrapper.className = "ps-markdown-code-block";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ps-markdown-code-copy";
      button.title = "Copy code";
      button.setAttribute("aria-label", "Copy code");
      button.innerHTML = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7">' +
        '<rect x="8" y="8" width="12" height="13" rx="2"></rect><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"></path></svg>' +
        '<span role="status" aria-live="polite"></span>';
      pre.before(wrapper);
      wrapper.append(button, pre);
      buttons.set(button, pre.firstElementChild);
      wrappers.push(wrapper);
    });

    function resetFeedback() {
      if (timer) window.clearTimeout(timer);
      timer = 0;
      if (feedbackButton) {
        feedbackButton.title = "Copy code";
        feedbackButton.setAttribute("aria-label", "Copy code");
        feedbackButton.querySelector("span").textContent = "";
      }
      feedbackButton = null;
    }

    async function onCopy(event) {
      const button = event.target.closest(".ps-markdown-code-copy");
      const code = buttons.get(button);
      if (!code || copying) return;
      copying = true;
      button.setAttribute("aria-disabled", "true");
      resetFeedback();
      let ok = false;
      try {
        // Read the displayed code only on demand. Never include controls, trim,
        // or cache a second copy of every code block during rendering.
        ok = await core.copyTextToClipboard(code.textContent || "");
      } catch (_) {
        // Clipboard denial must not affect the document or its navigation.
      } finally {
        copying = false;
      }
      if (!active) return;
      button.removeAttribute("aria-disabled");
      const message = ok ? "Copied" : "Copy failed";
      button.title = message;
      button.setAttribute("aria-label", message);
      button.querySelector("span").textContent = message;
      feedbackButton = button;
      timer = window.setTimeout(resetFeedback, 1500);
    }

    markdown.addEventListener("click", onCopy);
    return function () {
      active = false;
      markdown.removeEventListener("click", onCopy);
      resetFeedback();
      buttons.clear();
      wrappers.forEach(wrapper => wrapper.replaceWith(wrapper.querySelector("pre")));
    };
  }

  function disposeMarkdownToc() {
    if (dispose) dispose();
    dispose = null;
  }

  function headingLabel(heading) {
    const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
    let text = "";
    let node;
    let count = 0;
    while (text.length < 200 && count++ < 64 && (node = walker.nextNode())) {
      text += node.substringData(0, 200 - text.length);
    }
    return text.replace(/\s+/g, " ").trim() || "Untitled heading";
  }

  function initMarkdownToc(root) {
    disposeMarkdownToc();
    const markdown = root && root.querySelector(".plotsrv-markdown");
    if (!markdown) return;
    if (preference.view !== app.config.activeViewId) {
      preference = { view: app.config.activeViewId, open: false, depth: 3 };
    }
    const inline = markdown.classList.contains("plotsrv-markdown--sanitized");
    const disposeCopies = inline ? initCodeCopies(markdown) : function () {};
    const prefix = "ps-md-toc-" + (++serial);
    const shell = document.createElement("div");
    shell.className = "ps-markdown-shell";
    shell.innerHTML =
      '<div class="artifact-toolbar ps-markdown-toolbar">' +
        '<button type="button" class="artifact-btn" data-markdown-toc-toggle aria-expanded="false">TOC</button>' +
      '</div><div class="ps-markdown-layout">' +
        '<aside class="ps-markdown-toc" hidden aria-label="Table of contents">' +
          '<div class="ps-markdown-toc__title"><strong>Contents</strong>' +
            '<button type="button" data-markdown-toc-close aria-label="Close table of contents">×</button></div>' +
          '<label class="ps-markdown-toc__depth">Heading depth <select aria-label="Heading depth">' +
            [1, 2, 3, 4, 5, 6].map(level => '<option value="' + level + '">' +
              (level === 1 ? 'H1 only' : 'H1–H' + level) + '</option>').join("") +
          '</select></label><nav aria-label="Markdown headings"><ol></ol></nav>' +
          '<p class="ps-markdown-toc__note" role="status"></p>' +
        '</aside></div>';
    const layout = shell.querySelector(".ps-markdown-layout");
    const toggle = shell.querySelector("[data-markdown-toc-toggle]");
    const sidebar = shell.querySelector("aside");
    const close = shell.querySelector("[data-markdown-toc-close]");
    const select = shell.querySelector("select");
    const list = shell.querySelector("ol");
    const note = shell.querySelector("[role=status]");
    sidebar.id = prefix;
    toggle.setAttribute("aria-controls", prefix);
    toggle.title = "Table of contents — jump to a Markdown heading";
    markdown.before(shell);
    layout.appendChild(markdown);
    select.value = String(preference.depth);
    let headings = null;
    let limited = false;

    function discover() {
      headings = [];
      // Work only on the rendered preview, and only when opened. Avoid collecting
      // an unbounded NodeList when a user has disabled server display limits.
      const walker = document.createTreeWalker(markdown, NodeFilter.SHOW_ELEMENT);
      let node;
      let visited = 0;
      while ((node = walker.nextNode())) {
        if (++visited > 10000 || headings.length >= 1000) {
          limited = true;
          break;
        }
        if (!/^H[1-6]$/.test(node.tagName)) continue;
        const entry = {
          node: node, level: Number(node.tagName[1]), label: headingLabel(node),
          id: node.getAttribute("id"), tabindex: node.getAttribute("tabindex"),
        };
        node.id = prefix + "-heading-" + headings.length;
        node.setAttribute("tabindex", "-1");
        headings.push(entry);
      }
    }

    function renderList() {
      if (!headings) discover();
      list.replaceChildren();
      let visible = 0;
      headings.forEach((heading, index) => {
        if (heading.level > preference.depth) return;
        const item = document.createElement("li");
        item.style.setProperty("--toc-level", heading.level - 1);
        const link = document.createElement("a");
        link.href = "#" + heading.node.id;
        link.dataset.markdownHeading = String(index);
        link.textContent = heading.label;
        item.appendChild(link);
        list.appendChild(item);
        visible += 1;
      });
      note.textContent = !headings.length ? "No headings in this preview." :
        !visible ? "No headings at this depth. Choose a deeper level." : "";
      if (limited) note.textContent += " TOC limited to the first 1,000 headings or 10,000 document elements.";
    }

    function setOpen(open, focus) {
      preference.open = open;
      sidebar.hidden = !open;
      shell.classList.toggle("ps-markdown-shell--toc", open);
      toggle.setAttribute("aria-expanded", String(open));
      if (open) renderList();
      if (focus) (open ? select : toggle).focus({ preventScroll: true });
    }

    function onToggle() { setOpen(!preference.open, true); }
    function onClose() { setOpen(false, true); }
    function onDepth() {
      preference.depth = Number(select.value);
      renderList();
    }
    function onKey(event) {
      if (event.key === "Escape" && preference.open) {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    }
    function onNavigate(event) {
      const link = event.target.closest("[data-markdown-heading]");
      if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      const heading = headings[Number(link.dataset.markdownHeading)];
      if (!heading) return;
      event.preventDefault(); // Heading navigation must not change Compare/URL history.
      if (window.matchMedia("(max-width: 700px)").matches) setOpen(false, false);
      heading.node.focus({ preventScroll: true });
      heading.node.scrollIntoView({ block: "start", behavior: "instant" });
    }

    toggle.addEventListener("click", onToggle);
    close.addEventListener("click", onClose);
    select.addEventListener("change", onDepth);
    sidebar.addEventListener("click", onNavigate);
    shell.addEventListener("keydown", onKey);
    if (inline) setOpen(preference.open, false);
    else {
      // Never grant same-origin/scripts access to an isolated Markdown document.
      toggle.disabled = true;
      toggle.title = markdown.classList.contains("plotsrv-markdown--iframe") ?
        "TOC is available for sanitized Markdown; this document uses an isolated HTML sandbox." :
        "TOC is available when Markdown renders successfully.";
    }

    dispose = function () {
      disposeCopies();
      toggle.removeEventListener("click", onToggle);
      close.removeEventListener("click", onClose);
      select.removeEventListener("change", onDepth);
      sidebar.removeEventListener("click", onNavigate);
      shell.removeEventListener("keydown", onKey);
      if (headings) headings.forEach(heading => {
        for (const name of ["id", "tabindex"]) {
          if (heading[name] === null) heading.node.removeAttribute(name);
          else heading.node.setAttribute(name, heading[name]);
        }
      });
      headings = null;
      shell.replaceWith(markdown);
    };
  }

  core.disposeMarkdownToc = disposeMarkdownToc;
  app.renderers.initMarkdownToc = initMarkdownToc;
})();
