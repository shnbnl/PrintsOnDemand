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
