"use strict";

// The upload form stays native. A one-use flag only enhances its Shop destination.
(() => {
  const key = "pod:upload-to-shop-reveal";
  const nextForm = document.querySelector("[data-checkout-next-shop-form]");
  if (nextForm) {
    try { sessionStorage.removeItem(key); } catch (_) { /* Storage may be unavailable. */ }
    nextForm.addEventListener("submit", (event) => {
      if (!event.submitter?.matches("[data-checkout-next-shop]")) return;
      try { sessionStorage.setItem(key, "1"); } catch (_) { /* Normal navigation still works. */ }
    });
    return;
  }

  const workspace = document.querySelector("[data-shop-workspace]");
  if (!workspace) return;
  let fromUpload = false;
  try {
    fromUpload = sessionStorage.getItem(key) === "1";
    sessionStorage.removeItem(key);
  } catch (_) { /* Normal page display still works. */ }
  if (!fromUpload || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const message = document.querySelector("#map-message");
  document.body.classList.add("is-map-waiting");
  let started = false;
  let timeout;
  const observer = new MutationObserver(() => { if (message?.hidden) reveal(); });

  function reveal() {
    if (started) return;
    started = true;
    observer.disconnect();
    window.clearTimeout(timeout);
    document.body.classList.remove("is-map-waiting");
    document.body.classList.add("is-map-arriving");
    window.setTimeout(() => document.body.classList.remove("is-map-arriving"), 1150);
  }

  if (message?.hidden || !message) reveal();
  else {
    observer.observe(message, { attributes: true, attributeFilter: ["hidden"] });
    timeout = window.setTimeout(reveal, 2000);
  }
  window.addEventListener("pagehide", () => {
    observer.disconnect();
    window.clearTimeout(timeout);
    document.body.classList.remove("is-map-waiting", "is-map-arriving");
  });
})();
