"use strict";
(() => {
  const methods = [...document.querySelectorAll('input[name="payment_method"]')];
  const onlinePanel = document.querySelector('[data-online-payment]');
  const reference = document.querySelector('#payment_reference');
  function update() {
    const online = methods.find((method) => method.checked)?.value === 'ONLINE';
    onlinePanel.hidden = !online;
    reference.disabled = !online;
  }
  methods.forEach((method) => method.addEventListener('change', update));
  update();
})();
