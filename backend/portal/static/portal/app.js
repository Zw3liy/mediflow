'use strict';
const menu = document.querySelector('.menu-toggle');
if (menu) menu.addEventListener('click', () => {
  const open = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(open));
  document.getElementById(menu.getAttribute('aria-controls')).classList.toggle('menu-open', open);
});
document.querySelectorAll('[data-filter-table]').forEach(input => {
  input.addEventListener('input', () => {
    const table = document.getElementById(input.dataset.filterTable);
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    table.querySelectorAll('tbody tr:not(.filter-empty)').forEach(row => {
      const match = row.textContent.toLocaleLowerCase().includes(query);
      row.hidden = !match;
      if (match) visible++;
    });
    const status = document.querySelector(`[data-filter-status="${table.id}"]`);
    if (status) status.textContent = `${visible} matching rows in the displayed appointments.`;
    let empty = table.querySelector('.filter-empty');
    if (!empty) {
      empty = table.querySelector('tbody').insertRow();
      empty.className = 'filter-empty';
      const cell = empty.insertCell();
      cell.colSpan = table.querySelectorAll('thead th').length;
      cell.className = 'empty';
      cell.textContent = 'No displayed appointments match your search. Try a different name or clear the search.';
    }
    empty.hidden = visible > 0;
  });
});
