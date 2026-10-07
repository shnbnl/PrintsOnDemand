"use strict";

// Enhance desktop entry links without changing their native destinations.
(() => {
  const links = document.querySelectorAll("[data-landing-login], [data-landing-entry]");
  const hero = document.querySelector(".landing-hero");
  const visual = hero?.querySelector(".landing-hero-visual");
  if (!links.length || !hero || !visual) return;

  const motionAllowed = window.matchMedia("(min-width: 48.01rem) and (prefers-reduced-motion: no-preference)");
  let navigationTimer;

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
          event.shiftKey || event.altKey || link.target && link.target !== "_self" ||
          !motionAllowed.matches || getComputedStyle(visual).display === "none") return;

      event.preventDefault();
      if (navigationTimer) return;
      hero.classList.add("is-entry-exiting");
      navigationTimer = window.setTimeout(() => window.location.assign(link.href), 640);
    });
  });

  window.addEventListener("pagehide", () => window.clearTimeout(navigationTimer));
  window.addEventListener("pageshow", () => {
    navigationTimer = undefined;
    hero.classList.remove("is-entry-exiting");
  });
})();
