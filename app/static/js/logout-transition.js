"use strict";

// Keep the CSRF-protected POST intact while giving every account the same logo exit.
(() => {
  const forms = document.querySelectorAll("[data-logout-form]");
  const logo = document.querySelector(".site-header .brand-logo");
  if (!forms.length || !logo) return;

  const motionAllowed = window.matchMedia("(prefers-reduced-motion: no-preference)");
  let timer;
  let resubmitting = false;

  forms.forEach((form) => form.addEventListener("submit", (event) => {
    if (resubmitting || event.defaultPrevented || !motionAllowed.matches) return;
    event.preventDefault();
    if (timer) return;

    const bounds = logo.getBoundingClientRect();
    document.body.style.setProperty("--warp-x", `${bounds.left + bounds.width / 2}px`);
    document.body.style.setProperty("--warp-y", `${bounds.top + bounds.height / 2}px`);
    document.body.classList.add("is-logging-out");
    timer = window.setTimeout(() => {
      resubmitting = true;
      form.requestSubmit(event.submitter || undefined);
    }, 480);
  }));

  window.addEventListener("pagehide", () => window.clearTimeout(timer));
  window.addEventListener("pageshow", () => {
    timer = undefined;
    resubmitting = false;
    document.body.classList.remove("is-logging-out");
  });
})();
