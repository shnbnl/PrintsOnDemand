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
