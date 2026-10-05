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
        content.innerHTML = result.html;
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
    revision += 1;
    clearTimeout(timer);
    timer = setTimeout(updateQuote, 300);
  });
  form.addEventListener("submit", (event) => {
    if (pendingSelections) { event.preventDefault(); return; }
    clearTimeout(timer);
  });
})();
