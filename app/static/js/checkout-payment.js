"use strict";
(() => {
  const methods = [...document.querySelectorAll('input[name="payment_method"]')];
  const onlinePanel = document.querySelector('[data-online-payment]');
  const reference = document.querySelector('#payment_reference');
  if (!onlinePanel || !reference) return;
  function update() {
    const online = methods.find((method) => method.checked)?.value === 'ONLINE';
    onlinePanel.hidden = !online;
    reference.disabled = !online;
    reference.required = online;
    reference.setAttribute('aria-required', String(online));
  }
  methods.forEach((method) => method.addEventListener('change', update));
  update();
})();
