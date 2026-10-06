"use strict";
(() => {
  const form = document.querySelector("[data-shop-workspace]");
  if (!form) return;
  const select = form.querySelector('[name="shop_id"]');
  const content = form.querySelector("[data-workspace-content]");
  const error = form.querySelector("[data-workspace-error]");
  const notice = form.querySelector('[data-workspace-notice]');
  let queue = Promise.resolve();
  let revision = 0;
  let timer;
  let pendingSelections = 0;
  let activeFile;
  let committedShopId = select.value;
  let committedHTML = content.innerHTML;
  let previewRevision = 0;
  const picker = form.querySelector('[data-workspace-picker]');
  const search = form.querySelector('[data-shop-search]');
  const clearSearch = form.querySelector('[data-search-clear]');
  const searchStatus = form.querySelector('[data-search-status]');
  const noResults = form.querySelector('[data-search-empty]');
  const shopOptions = [...form.querySelectorAll('[data-shop-option]')];
  const mapToggle = form.querySelector('[data-map-toggle]');
  picker.hidden = Boolean(committedShopId);
  function filterShops() {
    const query = search.value.trim().toLocaleLowerCase();
    let shown = 0;
    shopOptions.forEach((option) => {
      option.hidden = !option.dataset.searchText.includes(query);
      if (!option.hidden) shown += 1;
    });
    clearSearch.hidden = !query;
    noResults.hidden = shown !== 0;
    searchStatus.textContent = shown ? `${shown} ${shown === 1 ? 'shop' : 'shops'} available. Choose one to continue.` : 'No shops match this search.';
  }
  search.addEventListener('input', filterShops);
  clearSearch.addEventListener('click', () => { search.value = ''; filterShops(); search.focus(); });
  picker.addEventListener('click', (event) => {
    const option = event.target.closest('[data-shop-option]');
    if (option) selectShop(option.dataset.shopOption);
  });
  content.addEventListener('click', (event) => {
    if (!event.target.closest('[data-change-shop]')) return;
    picker.hidden = false;
    search.focus();
  });
  mapToggle.addEventListener('click', () => {
    const showing = form.classList.toggle('is-map-open');
    mapToggle.textContent = showing ? 'Hide map' : 'Show map';
    mapToggle.setAttribute('aria-expanded', String(showing));
    if (showing) document.dispatchEvent(new Event('pod:show-map'));
  });
  function activateFile(id, recalculate = true) {
    const selector = content.querySelector('[data-file-selector]');
    if (![...selector.options].some(option => option.value === String(id))) id = selector.value;
    activeFile = String(id);
    selector.value = activeFile;
    content.querySelectorAll('[data-file-settings]').forEach(group => {
      group.hidden = group.dataset.fileSettings !== activeFile;
      if (!group.hidden) {
        if (recalculate) {
          group.querySelector('[data-total-printed-pages]')?.dispatchEvent(new Event('input', { bubbles: true }));
        }
      }
    });
  }
  activateFile(content.querySelector('[data-file-selector]').value);
  content.addEventListener('change', event => {
    if (event.target.matches('[data-file-selector]')) activateFile(event.target.value);
  });
  form.addEventListener('invalid', event => {
    const group = event.target.closest('[data-file-settings]');
    if (group) activateFile(group.dataset.fileSettings);
  }, true);

  function report(message) {
    error.textContent = message || "";
    error.hidden = !message;
  }
  async function send(data) {
    const response = await fetch(form.action, { method: "POST", body: data,
      headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("Your session could not be updated. Reload the page and try again.");
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Unable to update the print settings.");
    return result;
  }
  function restoreCommittedShop() {
    if (content.querySelector('[data-current-shop]')?.dataset.currentShop === committedShopId) return;
    content.innerHTML = committedHTML;
    activateFile(activeFile, false);
    requestAnimationFrame(() => content.classList.remove('is-switching'));
  }
  function previewShop(id) {
    const version = ++previewRevision;
    const shopId = String(id);
    if (![...select.options].some((option) => option.value === shopId) || !shopId) return;
    if (shopId === committedShopId) {
      restoreCommittedShop();
      return;
    }
    const stateVersion = revision;
    const data = new FormData(form);
    data.set('shop_id', shopId);
    data.set('intent', 'preview');
    queue = queue.then(async () => {
      try {
        const result = await send(data);
        if (version !== previewRevision || stateVersion !== revision || pendingSelections) return;
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          content.classList.add('is-switching');
          await new Promise(resolve => setTimeout(resolve, 120));
          if (version !== previewRevision || stateVersion !== revision || pendingSelections) return;
        }
        content.innerHTML = result.html;
        activateFile(activeFile, false);
        content.querySelector('[data-workspace-proceed]')?.setAttribute('disabled', '');
        requestAnimationFrame(() => content.classList.remove('is-switching'));
      } catch (issue) {
        // Hover previews are informational and should not interrupt checkout.
      }
    });
  }
  function selectShop(id) {
    if (![...select.options].some((option) => option.value === String(id))) return;
    if (!pendingSelections && committedShopId === String(id)) return;
    clearTimeout(timer);
    const version = ++revision;
    previewRevision += 1;
    select.value = String(id);
    pendingSelections += 1;
    form.querySelector("[data-workspace-proceed]").disabled = true;
    content.setAttribute("aria-busy", "true");
    content.inert = true;
    const data = new FormData(form);
    data.set("intent", "select");
    queue = queue.then(async () => {
      try {
        const result = await send(data);
        if (version !== revision) return;
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          content.classList.add('is-switching');
          await new Promise(resolve => setTimeout(resolve, 180));
          if (version !== revision) return;
        }
        content.innerHTML = result.html;
        committedShopId = String(result.shop_id);
        committedHTML = content.innerHTML;
        activateFile(activeFile);
        picker.hidden = true;
        shopOptions.forEach(option => option.setAttribute('aria-pressed', String(option.dataset.shopOption === committedShopId)));
        requestAnimationFrame(() => content.classList.remove('is-switching'));
        document.dispatchEvent(new CustomEvent("pod:shop-highlight", { detail: { id: result.shop_id } }));
        notice.textContent = result.notice || '';
        notice.hidden = !result.notice;
        report("");
      } catch (issue) {
        if (version === revision) {
          select.value = committedShopId;
          document.dispatchEvent(new CustomEvent("pod:shop-highlight", { detail: { id: select.value } }));
          restoreCommittedShop();
          report(issue.message);
        }
      } finally {
        pendingSelections -= 1;
        if (!pendingSelections) {
          if (version !== revision) content.classList.remove('is-switching');
          content.removeAttribute("aria-busy");
          content.inert = false;
          form.querySelector("[data-workspace-proceed]").disabled =
            !select.value || content.querySelector('[data-quote-valid]')?.dataset.quoteValid !== 'true';
        }
      }
    });
  }
  function updateQuote() {
    if (!select.value || pendingSelections) return;
    const version = ++revision;
    content.querySelector('[data-workspace-proceed]').disabled = true;
    content.querySelector('[data-quote-valid]').dataset.quoteValid = 'false';
    const data = new FormData(form);
    data.set("intent", "quote");
    const total = content.querySelector("[data-print-total]");
    total.textContent = "Updating…";
    content.querySelector('[data-print-subtotal]').textContent = 'Updating…';
    content.querySelector('[data-rush-fee]').textContent = 'Updating…';
    queue = queue.then(async () => {
      try {
        const result = await send(data);
        if (version !== revision) return;
        total.textContent = `${result.currency} ${result.total}`;
        content.querySelector('[data-print-subtotal]').textContent = `${result.currency} ${result.subtotal}`;
        content.querySelector('[data-rush-fee]').textContent = `${result.currency} ${result.rush_fee}`;
        content.querySelector('[data-quote-valid]').dataset.quoteValid = 'true';
        content.querySelector('[data-workspace-proceed]').disabled = false;
        content.querySelector("[data-quote-error]").hidden = true;
        report("");
      } catch (issue) {
        if (version !== revision) return;
        total.textContent = "Check print settings";
        content.querySelector('[data-print-subtotal]').textContent = '—';
        content.querySelector('[data-rush-fee]').textContent = '—';
        content.querySelector('[data-quote-valid]').dataset.quoteValid = 'false';
        content.querySelector('[data-workspace-proceed]').disabled = true;
        report(issue.message);
      }
    });
  }
  select.addEventListener("change", () => selectShop(select.value));
  document.addEventListener("pod:shop-selected", (event) => selectShop(event.detail.id));
  document.addEventListener("pod:shop-preview", (event) => previewShop(event.detail.id));
  document.addEventListener("pod:shop-preview-end", () => {
    previewRevision += 1;
    restoreCommittedShop();
  });
  form.querySelector("[data-load-shop]").hidden = true;
  form.addEventListener("input", (event) => {
    if (!event.target.closest("[data-workspace-content]")) return;
    if (event.target.matches('[data-file-selector]')) return;
    previewRevision += 1;
    restoreCommittedShop();
    if (event.target.matches('[data-price-choice], [data-paper-select], [data-color-select]')) {
      const group = event.target.closest('[data-file-settings]');
      const paperSelect = group.querySelector('[data-paper-select]');
      const colorSelect = group.querySelector('[data-color-select]');
      const rates = [...group.querySelectorAll('[data-price-choice]')];
      let [paper, mode] = event.target.matches('[data-price-choice]')
        ? event.target.value.split(':') : [paperSelect.value, colorSelect.value];
      let chosen = rates.find(rate => rate.value === `${paper}:${mode}`);
      const message = group.querySelector('[data-configuration-message]');
      if (!chosen) {
        chosen = rates.find(rate => rate.value.startsWith(`${paper}:`)) || rates[0];
        if (chosen) {
          [, mode] = chosen.value.split(':');
          message.textContent = `${mode === 'COLOR' ? 'Color' : 'Grayscale'} is the available output for ${paper}.`;
          message.hidden = false;
        }
      } else message.hidden = true;
      if (!chosen) return;
      [paper, mode] = chosen.value.split(':');
      paperSelect.value = paper;
      colorSelect.value = mode;
      [...colorSelect.options].forEach(option => {
        option.disabled = !rates.some(rate => rate.value === `${paper}:${option.value}`);
      });
      chosen.checked = true;
      group.querySelector('[data-selection-summary]').textContent = `${paper} · ${mode === 'COLOR' ? 'Color' : 'Grayscale'}`;
    }
    revision += 1;
    clearTimeout(timer);
    content.querySelector('[data-print-total]').textContent = 'Updating…';
    content.querySelector('[data-workspace-proceed]').disabled = true;
    content.querySelector('[data-quote-valid]').dataset.quoteValid = 'false';
    timer = setTimeout(updateQuote, 300);
  });
  form.addEventListener("submit", (event) => {
    if (pendingSelections || content.querySelector('[data-current-shop]')?.dataset.currentShop !== committedShopId
        || content.querySelector('[data-quote-valid]')?.dataset.quoteValid !== 'true') {
      event.preventDefault();
      return;
    }
    clearTimeout(timer);
  });
})();
