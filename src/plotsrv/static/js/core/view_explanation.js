(function () {
  "use strict";
  const {core, state, config} = window.PLOTSRV;
  const text = value => typeof value === "string" ? value.slice(0, 512).trim() : "";
  function sync() {
    const about = document.getElementById("view-about");
    if (!about) return;
    const source = (config.viewCatalogue || []).find(view => view.view_id === config.activeViewId);
    const presentation = core.getPresentationExplanation ? core.getPresentationExplanation() : null;
    const featured = (config.featuredViews || []).find(view => (view.view_id || view.view) === config.activeViewId);
    const caption = presentation ? text(presentation.caption) || text(source && source.description)
      : text(featured && featured.caption) || text(source && source.description);
    const origin = presentation && text(presentation.caption) ? presentation.origin
      : !presentation && text(featured && featured.caption) ? "Featured presentation" : "Source description";
    const historical = state.currentSnapshot || state.streamHistoricalSessionId;
    const scope = historical ? "Current description and presentation settings; not stored with the inspected version." : origin;
    if (!caption) {
      if (about.contains(document.activeElement)) {
        const target = document.querySelector('.ps-viewselect__btn') || document.getElementById('header-status-button');
        if (target) target.focus();
      }
      about.open = false;
    }
    const summary = about.querySelector('summary');
    about.dataset.disabled = caption ? "false" : "true";
    summary.setAttribute('aria-disabled', caption ? 'false' : 'true');
    summary.tabIndex = caption ? 0 : -1;
    summary.title = caption ? 'About this view' : 'No information explanation has been set for this view';
    for (const [id, value] of [["view-about-text", caption], ["view-about-scope", scope]]) {
      const node = document.getElementById(id);
      if (node.textContent !== value) node.textContent = value;
    }
  }
  function bind() {
    const about = document.getElementById("view-about");
    if (!about || about.dataset.bound) return;
    about.dataset.bound = "1";
    about.querySelector('summary').addEventListener('click', event => {
      if (about.dataset.disabled === 'true') event.preventDefault();
    });
    const close = () => {about.open = false; about.querySelector('summary').focus();};
    about.querySelector('button').addEventListener('click', close);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && about.open) {event.preventDefault(); close();}
    });
    sync();
  }
  core.syncViewExplanation = sync;
  core.bindViewExplanation = bind;
})();
