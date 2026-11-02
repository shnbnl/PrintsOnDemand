"use strict";
(() => {
  const form = document.querySelector('[data-staff-professor-form]');
  if (!form) return;
  const { faculties, locations } = JSON.parse(document.getElementById('staff-professor-options').textContent);
  const department = form.querySelector('[name="department"]');
  const faculty = form.querySelector('[name="faculty"]');
  const office = form.querySelector('[name="office"]');
  let lastLocation = locations[department.value] || '';
  function update() {
    const saved = faculty.value;
    const choices = faculties[department.value] || [];
    faculty.replaceChildren(new Option(choices.length ? 'Select a Faculty / program' : 'Not applicable', ''));
    choices.forEach(value => faculty.add(new Option(value, value)));
    if (choices.includes(saved)) faculty.value = saved;
    faculty.required = choices.length > 0;
    if (!office.value || office.value === lastLocation) office.value = locations[department.value] || '';
    lastLocation = locations[department.value] || '';
  }
  department.addEventListener('change', update);
  update();
})();
