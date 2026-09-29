/* plotsrv source: js/config_ui.js */
/* Temporary configuration tool only. Never included in the dashboard bundle. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let key = "", state = null, reviewId = null, activeRegion = "branding", busy = false;
  let imageUrls = [], previewTimer = null;
  const notice = (text) => { $("notice").textContent = text; };
  async function request(path, {json, raw, name} = {}) {
    const headers = {"X-Plotsrv-UI-Session": key};
    const opts = {headers, cache: "no-store", credentials: "omit", redirect: "error"};
    if (json !== undefined || raw !== undefined) {
      opts.method = "POST";
      headers["X-Plotsrv-UI-Action"] = "edit";
      if (raw !== undefined) { opts.body = raw; headers["X-Image-Name"] = name; }
      else { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(json); }
    }
    const abort = new AbortController(); opts.signal = abort.signal;
    const timer = setTimeout(() => abort.abort(), 10000);
    let response;
    try {
      const remote = await fetch(path, opts);
      const bytes = await remote.arrayBuffer();
      response = new Response(remote.status === 204 ? null : bytes, {status: remote.status, headers: remote.headers});
    } finally { clearTimeout(timer); }
    if (!response.ok) {
      if (response.status === 403) key = "";
      const error = await response.json().catch(() => null);
      throw new Error(error?.error || `Editor request failed (${response.status}). Reopen the session if it has expired.`);
    }
    return response;
  }
  async function run(operation) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("#editor button, #editor input, #save, #unlock button").forEach((el) => { el.disabled = true; });
    try { await operation(); }
    catch (error) { const message = error.message || "Editor operation failed. Nothing was confirmed."; notice(message); if ($("review-dialog").open) $("review-error").textContent = message; }
    finally {
      busy = false;
      document.querySelectorAll("#editor button, #editor input, #save, #unlock button").forEach((el) => { el.disabled = false; });
    }
  }
  function schedulePreview(delay = 500) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      if (busy) { schedulePreview(150); return; }
      previewTimer = null;
      run(() => apply());
    }, delay);
  }
  function region(name, focus = true) {
    activeRegion = name;
    document.querySelectorAll("[data-region]").forEach((el) => el.setAttribute("aria-pressed", String(el.dataset.region === name)));
    document.querySelectorAll("fieldset[data-group]").forEach((el) => { el.hidden = el.dataset.group !== name; });
    if (focus) document.querySelector(`fieldset[data-group="${name}"] input`)?.focus();
  }
  function fields() {
    $("fields").replaceChildren();
    const groups = {};
    for (const [id, spec] of Object.entries(state.fields)) {
      if (!groups[spec.region]) {
        const set = document.createElement("fieldset"); set.dataset.group = spec.region;
        const title = document.createElement("legend"); title.textContent = {branding: "Logo and header", controls: "Visible controls", footer: "Lower bar"}[spec.region];
        set.append(title); groups[spec.region] = set; $("fields").append(set);
      }
      const row = document.createElement("div"); row.className = "setting";
      const label = document.createElement("label"); label.htmlFor = `field-${id}`; label.textContent = spec.label;
      const input = document.createElement("input"); input.id = `field-${id}`; input.dataset.key = id;
      if (id === "logo" || id === "favicon") {
        input.type = "file"; input.accept = "image/png,image/jpeg";
        input.addEventListener("change", () => run(async () => {
          const file = input.files[0];
          if (!file) return;
          if (file.size > 2 * 1024 * 1024) throw new Error("Images must be at most 2 MiB.");
          const path = $(`field-${id}-path`); path.dataset.dirty = "false"; path.value = state.values[id];
          await apply(false);
          state = await (await request(`/api/upload/${id}`, {raw: file, name: file.name})).json();
          fields(); await preview(); notice("Image staged. Review and Save to keep it.");
        }));
        const reset = document.createElement("button"); reset.type = "button"; reset.textContent = `Reset ${spec.label.toLowerCase()}`;
        reset.addEventListener("click", () => run(async () => {
          const path = $(`field-${id}-path`); path.dataset.dirty = "false"; path.value = state.values[id];
          await apply(false);
          state = await (await request("/api/draft", {json: {[id]: ""}})).json();
          fields(); await preview(); notice("Default image selected in the draft.");
        }));
        const current = document.createElement("p"); current.className = "muted"; current.textContent = state.values[id] ? `Configured: ${state.values[id]}` : "Built-in image";
        const pathLabel = document.createElement("label"); pathLabel.htmlFor = `field-${id}-path`; pathLabel.textContent = "Or use an existing file path";
        const path = document.createElement("input"); path.id = `field-${id}-path`; path.dataset.key = id; path.type = "text";
        path.value = state.values[id]; path.maxLength = 512; path.placeholder = "Path on the server running plotsrv";
        path.addEventListener("input", () => { path.dataset.dirty = "true"; schedulePreview(); });
        row.append(label, input, pathLabel, path, reset, current);
      } else {
        input.type = typeof state.values[id] === "boolean" ? "checkbox" : "text";
        if (input.type === "checkbox") input.checked = state.values[id];
        else { input.value = state.values[id]; input.maxLength = 512; }
        input.addEventListener("input", () => { input.dataset.dirty = "true"; schedulePreview(input.type === "checkbox" ? 0 : 500); });
        row.append(label, input);
      }
      const help = document.createElement("p"); help.id = `help-${id}`; help.textContent = spec.help;
      input.setAttribute("aria-describedby", help.id); row.append(help); groups[spec.region].append(row);
    }
    region(activeRegion, false);
  }
  async function apply(refresh = true) {
    const patch = {};
    document.querySelectorAll("#fields input[data-key]:not([type=file])").forEach((input) => {
      const value = input.type === "checkbox" ? input.checked : input.value;
      if (input.dataset.dirty === "true" && value !== state.values[input.dataset.key]) patch[input.dataset.key] = value;
    });
    if (Object.keys(patch).length) state = await (await request("/api/draft", {json: patch})).json();
    for (const id of Object.keys(patch)) {
      const input = document.getElementById(`field-${id}${id === "logo" || id === "favicon" ? "-path" : ""}`);
      if (input && input.type === "text") input.value = state.values[id];
      if (input) input.dataset.dirty = "false";
    }
    reviewId = null;
    if (refresh) { await preview(); notice("Preview updated. Changes are still unsaved."); }
  }
  async function preview() {
    $("preview-page-title").textContent = state.values.page_title;
    const markup = await (await request("/api/preview")).text();
    imageUrls.forEach((url) => URL.revokeObjectURL(url)); imageUrls = [];
    let logo = null;
    const response = await request("/api/image/logo");
    if (response.status !== 204) { logo = URL.createObjectURL(await response.blob()); imageUrls.push(logo); }
    const icon = await request("/api/image/favicon");
    if (icon.status !== 204) { const url = URL.createObjectURL(await icon.blob()); imageUrls.push(url); $("preview-favicon").src = url; }
    else $("preview-favicon").src = "/static/ui-images/plotsrv_icon_logo.png";
    const iframe = $("preview");
    await new Promise((resolve, reject) => {
    const deadline = setTimeout(() => { iframe.onload = null; iframe.removeAttribute("srcdoc"); reject(new Error("Preview did not finish loading. Try Update preview again.")); }, 10000);
    iframe.onload = async () => {
      try {
      const doc = iframe.contentDocument;
      doc.documentElement.dataset.theme = $("theme").value;
      // Sandbox forbids scripts; remove executable attributes as another barrier.
      doc.querySelectorAll("script").forEach((el) => el.remove());
      doc.querySelectorAll("*").forEach((el) => [...el.attributes].forEach((attr) => { if (attr.name.startsWith("on")) el.removeAttribute(attr.name); }));
      doc.querySelectorAll("button, input, select").forEach((el) => { el.disabled = true; });
      doc.querySelectorAll("a").forEach((el) => el.removeAttribute("href"));
      if (logo) doc.querySelector(".header-logo").src = logo;
      doc.querySelectorAll("#header-status-label").forEach((el) => { el.textContent = "Latest"; });
      doc.querySelectorAll("#header-status-context").forEach((el) => { el.textContent = "Example data"; });
      const snapshot = doc.querySelector("#history-select option"); if (snapshot) snapshot.textContent = "Example snapshot";
      const targets = [["preview-branding", "branding"], ["preview-controls", "controls"]];
      const lower = doc.querySelector(".ps-bottom-bar"); if (lower) { lower.id = "preview-footer"; targets.push(["preview-footer", "footer"]); }
      for (const [id, group] of targets) {
        const el = doc.getElementById(id); if (!el) continue;
        el.tabIndex = 0; el.setAttribute("role", "button"); el.setAttribute("aria-label", `Edit ${group} settings`);
        el.addEventListener("click", () => region(group));
        el.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); region(group); } });
      }
      await Promise.allSettled([...doc.images].map((img) => img.decode()));
      resolve();
      } catch (error) { reject(error); } finally { clearTimeout(deadline); }
    };
    iframe.srcdoc = markup;
    });
  }
  $("unlock").addEventListener("submit", (event) => { event.preventDefault(); run(async () => {
    key = $("session").value.trim(); $("session").value = "";
    state = await (await request("/api/state")).json();
    $("config-path").textContent = state.path; $("scope").textContent = `Scope: ${state.scope}`;
    $("asset-directory").textContent = `New images: ${state.assets_dir}. Existing files are never overwritten.`;
    $("login").hidden = true; $("editor").hidden = false; fields(); await preview(); region("branding"); notice("Draft opened. Preview uses example data only.");
  }); });
  document.querySelectorAll("[data-region]").forEach((el) => el.addEventListener("click", () => region(el.dataset.region)));
  $("theme").addEventListener("change", () => { document.documentElement.dataset.theme = $("theme").value; const doc = $("preview").contentDocument; if (doc) doc.documentElement.dataset.theme = $("theme").value; });
  $("settings").addEventListener("submit", (event) => { event.preventDefault(); run(() => apply()); });
  $("review").addEventListener("click", () => run(async () => {
    clearTimeout(previewTimer); previewTimer = null;
    await apply(false);
    const review = await (await request("/api/review", {json: {}})).json();
    reviewId = review.review_id; $("review-error").textContent = ""; $("diff").textContent = review.text; $("review-dialog").showModal(); $("back").focus();
  }));
  $("back").addEventListener("click", () => $("review-dialog").close());
  function finish(title, message) {
    clearTimeout(previewTimer); previewTimer = null;
    key = ""; reviewId = null; state = null; $("editor").hidden = true; $("review-dialog").close();
    $("preview").onload = null; $("preview").removeAttribute("srcdoc"); imageUrls.forEach((url) => URL.revokeObjectURL(url)); imageUrls = [];
    $("finished-title").textContent = title; $("finished-message").textContent = message; $("finished").hidden = false; notice("");
  }
  $("save").addEventListener("click", () => run(async () => {
    const result = await (await request("/api/save", {json: {review_id: reviewId}})).json();
    finish("Saved", `${result.message} Config: ${result.path}${result.backup ? ` Backup: ${result.backup}` : ""}`);
  }));
  $("cancel").addEventListener("click", () => run(async () => {
    const result = await (await request("/api/cancel", {json: {}})).json(); finish("Cancelled", result.message);
  }));
})();

