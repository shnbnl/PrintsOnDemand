"use strict";

// Keep the CSRF-protected POST intact while the current workspace closes.
(() => {
  const forms = document.querySelectorAll("[data-logout-form]");
  if (!forms.length) return;

  const motionAllowed = window.matchMedia("(prefers-reduced-motion: no-preference)");
  let timer;
  let resubmitting = false;

  forms.forEach((form) => form.addEventListener("submit", (event) => {
    if (resubmitting || event.defaultPrevented || !motionAllowed.matches) return;
    event.preventDefault();
    if (timer) return;

    document.body.classList.add("is-logging-out");
    timer = window.setTimeout(() => {
      resubmitting = true;
      form.requestSubmit(event.submitter || undefined);
    }, 520);
  }));

  window.addEventListener("pagehide", () => window.clearTimeout(timer));
  window.addEventListener("pageshow", () => {
    timer = undefined;
    resubmitting = false;
    document.body.classList.remove("is-logging-out");
  });
})();
