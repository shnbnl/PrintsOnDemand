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

  const shop = document.querySelector("#shop_id");
  const methods = [...document.querySelectorAll('input[name="destination"]')];
  const panels = [...document.querySelectorAll("[data-method-fields]")];
  function updateFulfillment() {
    if (!shop) return;
    const selectedShop = shop.selectedOptions[0];
    document.querySelectorAll('#pickup_slot, #delivery_slot').forEach((slotSelect) => {
      slotSelect.querySelectorAll('option[value]:not([value=""])').forEach((option) => {
        const [start, end] = option.value.split("-");
        option.disabled = !selectedShop?.dataset.opening ||
          start < selectedShop.dataset.opening || end > selectedShop.dataset.closing;
      });
      if (slotSelect.selectedOptions[0]?.disabled) slotSelect.value = "";
    });
    methods.forEach((input) => {
      const available = selectedShop?.dataset[input.value.toLowerCase()] === "1";
      input.disabled = !available;
      input.closest("[data-method-choice]").hidden = !available;
      if (!available) input.checked = false;
    });
    const selectedMethod = methods.find((input) => input.checked)?.value;
    panels.forEach((panel) => {
      const active = panel.dataset.methodFields === selectedMethod;
      panel.hidden = !active;
      panel.querySelectorAll("input, select, textarea").forEach((field) => {
        field.disabled = !active;
        field.required = active;
      });
    });
  }
  shop?.addEventListener("change", updateFulfillment);
  methods.forEach((input) => input.addEventListener("change", updateFulfillment));
  updateFulfillment();
})();
