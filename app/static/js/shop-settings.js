document.querySelectorAll('[data-service-toggle]').forEach((form) => {
  const toggle = form.querySelector('input[name="enabled"]');
  const status = form.querySelector('.service-switch-status');
  toggle.addEventListener('change', () => {
    status.textContent = toggle.checked ? 'On' : 'Off';
    form.requestSubmit();
  });
});

document.querySelectorAll('[data-payment-toggle]').forEach((row) => {
  const toggle = row.querySelector('input[type="checkbox"]');
  const status = row.querySelector('.service-switch-status');
  toggle.addEventListener('change', () => {
    status.textContent = toggle.checked ? 'On' : 'Off';
    row.closest('form').requestSubmit();
  });
});
