"use strict";

// The form still submits normally after this brief desktop-only visual cue.
(() => {
  const shell = document.querySelector("[data-auth-login-shell]");
  const form = shell?.querySelector("form[method='post']");
  const logo = shell?.querySelector(".auth-brand");
  if (!form || !logo) return;

  const motionAllowed = window.matchMedia("(min-width: 48.01rem) and (prefers-reduced-motion: no-preference)");
  let resubmitting = false;
  let timer;

  form.addEventListener("submit", (event) => {
    if (resubmitting || event.defaultPrevented || !motionAllowed.matches) return;
    const identity = form.querySelector("#email, #identifier, #name");
    const password = form.querySelector("#password");
    if (!identity?.value.trim() || !password?.value) return;

    event.preventDefault();
    if (timer) return;
    const bounds = logo.getBoundingClientRect();
    shell.style.setProperty("--warp-x", `${bounds.left + bounds.width / 2}px`);
    shell.style.setProperty("--warp-y", `${bounds.top + bounds.height / 2}px`);
    shell.classList.add("is-auth-warping");
    timer = window.setTimeout(() => {
      resubmitting = true;
      form.requestSubmit(event.submitter || undefined);
    }, 500);
  });

  window.addEventListener("pagehide", () => window.clearTimeout(timer));
  window.addEventListener("pageshow", () => {
    resubmitting = false;
    timer = undefined;
    shell.classList.remove("is-auth-warping");
  });
})();
