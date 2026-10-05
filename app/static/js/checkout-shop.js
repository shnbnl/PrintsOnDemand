"use strict";
(() => {
  const form = document.querySelector("[data-shop-workspace]");
  if (!form) return;
  const select = form.querySelector('[name="shop_id"]');
  const content = form.querySelector("[data-workspace-content]");
  const error = form.querySelector("[data-workspace-error]");
  let queue = Promise.resolve();
  let revision = 0;
  let timer;
  let pendingSelections = 0;
  let activeFile;
  const panel = form.querySelector('.workspace-panel');
  const toggle = form.querySelector('[data-panel-toggle]');
  function expandPanel() {
    panel.classList.remove('is-minimized');
    toggle.textContent = 'Minimize panel';
    toggle.setAttribute('aria-expanded', 'true');
  }
  toggle.addEventListener('click', () => {
    const minimized = panel.classList.toggle('is-minimized');
    toggle.textContent = minimized ? 'Open print settings' : 'Minimize panel';
    toggle.setAttribute('aria-expanded', String(!minimized));
  });
  function activateFile(id) {
    const selector = content.querySelector('[data-file-selector]');
    if (![...selector.options].some(option => option.value === String(id))) id = selector.value;
    activeFile = String(id);
    selector.value = activeFile;
    content.querySelectorAll('[data-file-settings]').forEach(group => {
      group.hidden = group.dataset.fileSettings !== activeFile;
    });
  }
  activateFile(content.querySelector('[data-file-selector]').value);
  content.addEventListener('change', event => {
    if (event.target.matches('[data-file-selector]')) activateFile(event.target.value);
  });
  form.addEventListener('invalid', event => {
    const group = event.target.closest('[data-file-settings]');
    if (group) { expandPanel(); activateFile(group.dataset.fileSettings); }
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
  function selectShop(id) {
    if (![...select.options].some((option) => option.value === String(id))) return;
    if (!pendingSelections && content.querySelector('[data-current-shop]')?.dataset.currentShop === String(id)) return;
    expandPanel();
    clearTimeout(timer);
    const version = ++revision;
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
        activateFile(activeFile);
        expandPanel();
        requestAnimationFrame(() => content.classList.remove('is-switching'));
        document.dispatchEvent(new CustomEvent("pod:shop-highlight", { detail: { id: result.shop_id } }));
        report("");
      } catch (issue) {
        if (version === revision) {
          select.value = content.querySelector("[data-current-shop]")?.dataset.currentShop || "";
          document.dispatchEvent(new CustomEvent("pod:shop-highlight", { detail: { id: select.value } }));
          report(issue.message);
        }
      } finally {
        pendingSelections -= 1;
        if (!pendingSelections) {
          if (version !== revision) content.classList.remove('is-switching');
          content.removeAttribute("aria-busy");
          content.inert = false;
          form.querySelector("[data-workspace-proceed]").disabled = !select.value;
        }
      }
    });
  }
  function updateQuote() {
    if (!select.value || pendingSelections) return;
    const version = ++revision;
    const data = new FormData(form);
    data.set("intent", "quote");
    const total = content.querySelector("[data-print-total]");
    total.textContent = "Updating…";
    queue = queue.then(async () => {
      try {
        const result = await send(data);
        if (version !== revision) return;
        total.textContent = `${result.currency} ${result.total}`;
        content.querySelector("[data-quote-error]").hidden = true;
        report("");
      } catch (issue) {
        if (version !== revision) return;
        total.textContent = "Check print settings";
        report(issue.message);
      }
    });
  }
  select.addEventListener("change", () => selectShop(select.value));
  document.addEventListener("pod:shop-selected", (event) => selectShop(event.detail.id));
  form.querySelector("[data-load-shop]").hidden = true;
  form.addEventListener("input", (event) => {
    if (!event.target.closest("[data-workspace-content]")) return;
    if (event.target.matches('[data-file-selector]')) return;
    if (event.target.matches('[data-price-choice]')) {
      const group = event.target.closest('[data-file-settings]');
      const [paper, mode] = event.target.value.split(':');
      group.querySelector('[name^="paper_size_"]').value = paper;
      group.querySelector('[name^="color_mode_"]').value = mode;
      group.querySelector('[data-selection-summary]').textContent = `${paper} · ${mode === 'COLOR' ? 'Color' : 'Grayscale'}`;
    }
    revision += 1;
    clearTimeout(timer);
    content.querySelector('[data-print-total]').textContent = 'Updating…';
    timer = setTimeout(updateQuote, 300);
  });
  form.addEventListener("submit", (event) => {
    if (pendingSelections) { event.preventDefault(); return; }
    clearTimeout(timer);
  });
})();
