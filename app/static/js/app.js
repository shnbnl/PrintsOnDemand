"use strict";

// Progressive presentation only; the server validates uploads and quantities.
const fileInput = document.querySelector(".file-input");
const selectedFileName = document.querySelector("#selected-file-name");

if (fileInput && selectedFileName) {
  fileInput.addEventListener("change", () => {
    const files = fileInput.files;
    selectedFileName.textContent = files && files.length
      ? files.length === 1 ? files[0].name : `${files.length} files selected`
      : "No file selected";
    selectedFileName.classList.toggle("is-selected", Boolean(files && files.length));
  });
}

document.querySelectorAll(".quantity-stepper").forEach((stepper) => {
  const input = stepper.querySelector('input[type="number"]');
  if (!input) return;

  stepper.querySelectorAll("button[data-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const direction = Number(button.dataset.step);
      if (direction > 0) input.stepUp();
      if (direction < 0) input.stepDown();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
});

// A native disclosure remains usable without JavaScript.
const mobileNavigation = document.querySelector(".mobile-nav");
if (mobileNavigation) {
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobileNavigation.open) {
      mobileNavigation.open = false;
      mobileNavigation.querySelector("summary").focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!mobileNavigation.contains(event.target)) mobileNavigation.open = false;
  });
}

// Associate server-rendered errors with controls without changing validation.
document.querySelectorAll(".field").forEach((field, index) => {
  const errors = field.querySelectorAll(".field-error");
  const control = field.querySelector("input, select, textarea");
  if (!errors.length || !control) return;
  const descriptions = (control.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
  errors.forEach((error, errorIndex) => {
    if (!error.id) error.id = `field-error-${index}-${errorIndex}`;
    descriptions.push(error.id);
  });
  control.setAttribute("aria-invalid", "true");
  control.setAttribute("aria-describedby", descriptions.join(" "));
});

// Feedback only: do not cancel submissions or disable named submit controls.
document.querySelectorAll('form[method="post"]:not(.inline-form)').forEach((form) => {
  form.addEventListener("submit", (event) => {
    queueMicrotask(() => {
      if (event.defaultPrevented) return;
      form.setAttribute("aria-busy", "true");
      let feedback = form.querySelector(".submission-feedback");
      if (!feedback) {
        feedback = document.createElement("p");
        feedback.className = "submission-feedback";
        feedback.setAttribute("role", "status");
        form.append(feedback);
      }
      feedback.textContent = form.enctype === "multipart/form-data" ? "Uploading your file…" : "Submitting…";
    });
  });
});

const professorDepartment = document.querySelector("[data-professor-department]");
const departmentInput = professorDepartment?.querySelector("select, input");
if (professorDepartment && departmentInput) {
  const registrationForm = professorDepartment.closest("form");
  const updateProfessorDepartment = () => {
    const professorSelected = registrationForm.querySelector('input[name="account_type"][value="PROFESSOR"]:checked') !== null;
    professorDepartment.hidden = !professorSelected;
    departmentInput.required = professorSelected;
  };
  registrationForm.querySelectorAll('input[name="account_type"]').forEach((input) => {
    input.addEventListener("change", updateProfessorDepartment);
  });
  updateProfessorDepartment();
}

window.addEventListener("pageshow", () => {
  document.querySelectorAll('form[aria-busy="true"]').forEach((form) => form.removeAttribute("aria-busy"));
  document.querySelectorAll(".submission-feedback").forEach((feedback) => feedback.remove());
});

window.addEventListener("pageshow", (event) => {
  if (event.persisted && window.location.pathname.startsWith("/account")) {
    window.location.reload();
  }
});
