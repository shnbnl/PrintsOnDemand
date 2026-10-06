"use strict";
// Delegation keeps count controls working when the Shop workspace is refreshed.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-count-step]");
  if (!button) return;
  const input = button.closest("[data-print-count]").querySelector('input[type="number"]');
  const current = Number(input.value);
  input.value = String(Math.min(Number(input.max), Math.max(Number(input.min),
    (Number.isInteger(current) ? current : Number(input.min)) + Number(button.dataset.countStep))));
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
});

function updatePrintedPageSummary(group) {
  if (!group) return;
  const count = Number(group.querySelector('[name^="quantity_"]')?.value);
  const output = group.querySelector('[data-total-printed-pages]');
  if (!output) return;
  if (group.dataset.pageCountCapable !== "true" || !group.dataset.documentPages) {
    output.textContent = group.dataset.pageCountCapable === "true"
      ? "Unable to determine" : "Not available for this file type";
    if (group.dataset.pageCountCapable === "true") {
      const estimate = group.querySelector('[data-file-print-total]');
      if (estimate) estimate.textContent = "Page count unavailable";
    } else {
      updateFileEstimate(group, count, 1);
    }
    return;
  }
  const pages = Number(group.dataset.documentPages);
  const printed = pages * count;
  output.textContent = Number.isInteger(count) && count > 0
    ? `${printed} ${printed === 1 ? 'page' : 'pages'}` : "Enter a valid copy count";
  updateFileEstimate(group, count, pages);
}

function updateFileEstimate(group, count, pages) {
  const output = group.querySelector('[data-file-print-total]');
  if (!output) return;
  if (group.dataset.pageCountCapable === "true" && !group.dataset.documentPages) {
    output.textContent = "Page count unavailable";
    return;
  }
  const selected = group.querySelector('[data-price-choice]:checked');
  const price = Number(selected?.dataset.unitPrice);
  const multiplier = group.dataset.pageCountCapable === "true" ? pages : 1;
  if (!Number.isFinite(price) || !Number.isInteger(count) || count < 1) {
    output.textContent = "Select a valid print setup";
    return;
  }
  output.textContent = `${group.dataset.currency} ${(price * multiplier * count).toFixed(2)}`;
}

document.addEventListener("input", (event) => {
  const group = event.target.closest("[data-file-settings]");
  if (!group) return;
  const count = Number(group.querySelector('[name^="quantity_"]')?.value);
  updatePrintedPageSummary(group);
  updateFileEstimate(group, count, Number(group.dataset.documentPages) || 1);
});
