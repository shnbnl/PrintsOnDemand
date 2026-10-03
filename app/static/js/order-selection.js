"use strict";

// Presentation only: the server validates selection, settings, and prices.
(() => {
  const toggles = [...document.querySelectorAll("[data-order-file-toggle]")];
  const count = document.querySelector("#order-file-count");
  if (!count) return;

  function update() {
    toggles.forEach((toggle) => {
      const card = toggle.closest("[data-order-file-card]");
      const selected = toggle.checked;
      card.classList.toggle("is-selected", selected);
      card.querySelector("[data-remove-file]").hidden = !selected;
      if (selected) card.querySelector("details").open = true;
    });
    const selected = toggles.filter((toggle) => toggle.checked).length;
    count.textContent = `${selected} file${selected === 1 ? "" : "s"} selected`;
  }

  toggles.forEach((toggle) => toggle.addEventListener("change", update));
  document.querySelectorAll("[data-remove-file]").forEach((button) => {
    button.addEventListener("click", () => {
      const toggle = button.closest("[data-order-file-card]").querySelector("[data-order-file-toggle]");
      toggle.checked = false;
      update();
      toggle.focus();
    });
  });
  update();
})();
