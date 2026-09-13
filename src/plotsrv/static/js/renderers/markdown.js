(function () {
  "use strict";

  const app = window.PLOTSRV;
  const core = app.core;
  let preference = { view: null, open: false, depth: 3 };
  let serial = 0;
  let dispose = null;

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
