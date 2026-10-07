"use strict";

// Enhance the desktop log-in link without changing its native destination.
(() => {
  const link = document.querySelector("[data-landing-login]");
  const hero = document.querySelector(".landing-hero");
  const visual = hero?.querySelector(".landing-hero-visual");
  if (!link || !hero || !visual) return;

  const motionAllowed = window.matchMedia("(min-width: 48.01rem) and (prefers-reduced-motion: no-preference)");
  let navigationTimer;

  link.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
        event.shiftKey || event.altKey || link.target && link.target !== "_self" ||
        !motionAllowed.matches || getComputedStyle(visual).display === "none") return;

    event.preventDefault();
    if (navigationTimer) return;
    hero.classList.add("is-login-exiting");
    navigationTimer = window.setTimeout(() => window.location.assign(link.href), 640);
  });

  window.addEventListener("pagehide", () => window.clearTimeout(navigationTimer));
  window.addEventListener("pageshow", () => {
    navigationTimer = undefined;
    hero.classList.remove("is-login-exiting");
  });
})();
