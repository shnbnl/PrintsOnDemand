"use strict";
(() => {
  document.querySelectorAll("[data-print-count]").forEach((control) => {
    const input = control.querySelector('input[type="number"]');
    control.querySelectorAll("[data-count-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const min = Number(input.min);
        const max = Number(input.max);
        const current = Number(input.value);
        const next = Math.min(max, Math.max(min, (Number.isInteger(current) ? current : min) + Number(button.dataset.countStep)));
        input.value = String(next);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
      });
    });
  });
})();
