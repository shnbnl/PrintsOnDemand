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

    if (from === "/shops" && to === "/shops/map") return "shop-to-map";
    if (from === "/shops/map" && to === "/shops") return "shop-to-list";

    const fromWorkspace = from === "/student" || from === "/professor";
    const fromCheckout = from.startsWith("/checkout/");
    const fromOrders = from === "/orders" || from.startsWith("/orders/");
    const fromAccount = from === "/account" || from.startsWith("/account/");
    const toHistory = to === "/orders";
    const toStart = to === "/checkout/upload";
    const toAccount = to === "/account";

    if (fromCheckout && toHistory) return "tab-to-history";
    if ((fromCheckout || fromOrders) && toAccount) return "tab-to-account";
    if (fromAccount && toHistory) return "tab-from-account";
    if ((fromOrders || fromAccount) && toStart) return "tab-to-start";
    if (fromWorkspace && (toStart || toHistory || toAccount)) return "workspace-entry";
    return null;
  };

  window.addEventListener("pageswap", (event) => {
    if (!event.viewTransition?.types || !event.activation) return;
    const type = transitionType(event.activation.from, event.activation.entry);
    if (type) event.viewTransition.types.add(type);
  });

  window.addEventListener("pagereveal", (event) => {
    const activation = window.navigation?.activation;
    if (!event.viewTransition?.types) return;
    // Safari supports cross-document transitions before it supports Navigation API.
    const type = activation
      ? transitionType(activation.from, activation.entry)
      : transitionType({ url: document.referrer }, { url: location.href });
    if (type) event.viewTransition.types.add(type);
  });
})();
