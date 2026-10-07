"use strict";

// The form still submits normally after this brief visual cue.
(() => {
  const shell = document.querySelector("[data-auth-submit-shell]");
  const form = shell?.querySelector("form[method='post']");
  const logo = shell?.querySelector(".auth-brand");
  if (!form || !logo) return;
  const registering = shell.hasAttribute("data-auth-register-shell");

  const motionAllowed = window.matchMedia("(prefers-reduced-motion: no-preference)");
  let resubmitting = false;
  let timer;

  form.addEventListener("submit", (event) => {
    if (resubmitting || event.defaultPrevented || !motionAllowed.matches) return;
    const password = form.querySelector("#password");
    if (registering) {
      const name = form.querySelector("#name");
      const email = form.querySelector("#email");
      const confirmation = form.querySelector("#confirm_password");
      const accountType = form.querySelector('input[name="account_type"]:checked');
      const department = form.querySelector("#professor_department");
      if (!name?.value.trim() || !email?.value.trim() || !password?.value ||
          !confirmation?.value || password.value !== confirmation.value ||
          !accountType || (accountType.value === "PROFESSOR" && !department?.value) ||
          !form.checkValidity()) return;
    } else {
      const identity = form.querySelector("#email, #identifier, #name");
      if (!identity?.value.trim() || !password?.value) return;
    }

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
