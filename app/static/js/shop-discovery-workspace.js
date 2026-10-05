"use strict";
(() => {
  const workspace = document.querySelector("[data-map-discovery-workspace]");
  if (!workspace) return;

  const panel = workspace.querySelector(".workspace-panel");
  const toggle = workspace.querySelector("[data-panel-toggle]");
  const content = workspace.querySelector("[data-workspace-content]");
  const shopPanels = [...workspace.querySelectorAll("[data-discovery-panel]")];
  let switchTimer;
  let settleTimer;
  let committedShopId = content.dataset.currentShop;

  toggle.addEventListener("click", () => {
    const minimized = panel.classList.toggle("is-minimized");
    toggle.setAttribute("aria-expanded", String(!minimized));
    toggle.textContent = minimized ? "Open shop details" : "Minimize details";
  });

  function displayShop(id) {
    const selectedId = String(id);
    const nextPanel = shopPanels.find((item) => item.dataset.discoveryPanel === selectedId);
    if (!nextPanel || content.dataset.currentShop === selectedId) return;

    clearTimeout(switchTimer);
    clearTimeout(settleTimer);
    content.setAttribute("aria-busy", "true");
    content.classList.add("is-switching");
    const changePanel = () => {
      shopPanels.forEach((item) => { item.hidden = item !== nextPanel; });
      content.dataset.currentShop = selectedId;
      requestAnimationFrame(() => content.classList.remove("is-switching"));
      settleTimer = window.setTimeout(() => content.removeAttribute("aria-busy"), 220);
    };

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) changePanel();
    else switchTimer = window.setTimeout(changePanel, 105);
  }

  document.addEventListener("pod:shop-selected", (event) => {
    committedShopId = String(event.detail.id);
    displayShop(committedShopId);
  });
  document.addEventListener("pod:shop-preview", (event) => displayShop(event.detail.id));
  document.addEventListener("pod:shop-preview-end", () => displayShop(committedShopId));
})();
