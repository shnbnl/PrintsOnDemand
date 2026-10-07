"use strict";

// The same native links keep working; supported browsers animate only these routes.
(() => {
  const pathOf = (entry) => {
    if (!entry?.url) return null;
    try {
      const url = new URL(entry.url);
      return url.origin === location.origin ? url.pathname.replace(/\/$/, "") || "/" : null;
    } catch (_) {
      return null;
    }
  };

  const transitionType = (fromEntry, toEntry) => {
    const from = pathOf(fromEntry);
    const to = pathOf(toEntry);
    if (!from || !to || from === to) return null;

    const fromWorkspace = from === "/student" || from === "/professor";
    const fromCheckout = from.startsWith("/checkout/");
    const fromOrders = from === "/orders" || from.startsWith("/orders/");
    const toHistory = to === "/orders";
    const toStart = to === "/checkout/upload";

    if (fromCheckout && toHistory) return "tab-to-history";
    if (fromOrders && toStart) return "tab-to-start";
    if (fromWorkspace && (toStart || toHistory || to === "/account")) return "workspace-entry";
    return null;
  };

  window.addEventListener("pageswap", (event) => {
    if (!event.viewTransition?.types || !event.activation) return;
    const type = transitionType(event.activation.from, event.activation.entry);
    if (type) event.viewTransition.types.add(type);
  });

  window.addEventListener("pagereveal", (event) => {
    const activation = window.navigation?.activation;
    if (!event.viewTransition?.types || !activation) return;
    const type = transitionType(activation.from, activation.entry);
    if (type) event.viewTransition.types.add(type);
  });
})();
