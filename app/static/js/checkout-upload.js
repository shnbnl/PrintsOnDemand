"use strict";

(() => {
  const form = document.querySelector("[data-checkout-upload]");
  if (!form || !window.XMLHttpRequest || !window.FormData) return;

  const button = form.querySelector('button[type="submit"]');
  const files = form.querySelector('input[type="file"]');
  const display = form.querySelector("[data-upload-progress]");
  const bar = display.querySelector("progress");
  const status = display.querySelector("[data-upload-status]");
  let uploading = false;

  function finishWithError(message) {
    uploading = false;
    button.disabled = false;
    files.disabled = false;
    bar.hidden = true;
    status.setAttribute("role", "alert");
    status.textContent = message;
  }

  files.addEventListener("change", () => {
    if (!uploading) display.hidden = true;
  });

  form.addEventListener("submit", (event) => {
    if (uploading) {
      event.preventDefault();
      return;
    }
    if (!form.reportValidity()) return;
    event.preventDefault();
    const maxSize = Number(form.dataset.maxFileBytes);
    const selectedFiles = [...files.files];
    if (selectedFiles.some((file) => file.size > maxSize)) {
      display.hidden = false;
      finishWithError("A selected file is too large. Choose a smaller file.");
      return;
    }
    if (selectedFiles.reduce((size, file) => size + file.size, 0) > maxSize) {
      display.hidden = false;
      finishWithError("The combined upload is too large. Add fewer files at a time.");
      return;
    }
    const data = new FormData(form);
    const request = new XMLHttpRequest();
    request.open("POST", form.action);
    request.setRequestHeader("Accept", "application/json");

    uploading = true;
    button.disabled = true;
    files.disabled = true;
    display.hidden = false;
    bar.hidden = false;
    bar.value = 0;
    status.setAttribute("role", "status");
    status.textContent = "Uploading files…";

    request.upload.addEventListener("progress", (progress) => {
      if (!progress.lengthComputable) return;
      const percent = Math.min(100, Math.round(100 * progress.loaded / progress.total));
      bar.value = percent;
      status.textContent = `Uploading files… ${percent}%`;
    });
    request.upload.addEventListener("load", () => {
      bar.removeAttribute("value");
      status.textContent = "Upload received. Checking files and document pages…";
    });
    request.addEventListener("load", () => {
      let result;
      try {
        result = JSON.parse(request.responseText);
      } catch (error) {
        finishWithError("Upload could not be completed. Reload the page and try again.");
        return;
      }
      if (request.status >= 200 && request.status < 300 && result.redirect) {
        status.textContent = "Files are ready. Opening your order…";
        window.location.assign(result.redirect);
        return;
      }
      finishWithError(result.error || "Upload could not be completed. Try again.");
    });
    request.addEventListener("error", () => {
      finishWithError("Connection lost while uploading. Check your connection and try again.");
    });
    try {
      request.send(data);
    } catch (error) {
      finishWithError("Upload could not be started. Try again.");
    }
  });

  window.addEventListener("pageshow", () => {
    if (!uploading) return;
    uploading = false;
    button.disabled = false;
    files.disabled = false;
    display.hidden = true;
  });
})();
