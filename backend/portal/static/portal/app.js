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

const notificationPanel = document.querySelector('[data-notification-practice]');
if (notificationPanel) {
  const practice = notificationPanel.dataset.notificationPractice;
  const list = document.getElementById('notification-list');
  let lastContent = '';
  let busy = false;
  async function refreshNotifications() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      const response = await fetch(`/app/notifications/?practice=${encodeURIComponent(practice)}`, {credentials:'same-origin', cache:'no-store'});
      if (!response.ok || response.redirected) return;
      const data = await response.json();
      const content = JSON.stringify(data);
      if (lastContent === content) return;
      lastContent = content;
      document.getElementById('unread-count').textContent = `${data.unread} unread`;
      const queue = document.getElementById('next-patient');
      if (queue) {
        const visit = data.next_patient;
        const label = document.createElement('span'); label.className = 'eyebrow'; label.textContent = 'NEXT PATIENT · YOUR QUEUE';
        const name = document.createElement('h2'); name.textContent = visit ? visit.patient : 'No patients waiting';
        queue.replaceChildren(label, name);
        if (visit) {
          [visit.time + ' · ' + visit.service, 'Reported symptoms: ' + visit.symptoms, 'Blood pressure: ' + visit.bp].forEach(text => {
            const detail = document.createElement('p'); detail.textContent = text; queue.append(detail);
          });
          const state = document.createElement('span'); state.className = 'badge';
          state.textContent = visit.called ? 'Patient called' : visit.approved ? 'Approved by you' : 'Reception approved · awaiting your review';
          queue.append(state);
          const token = document.querySelector('input[name="csrfmiddlewaretoken"]');
          const operation = !visit.approved ? 'doctor-approve' : visit.can_call ? 'call' : null;
          if (token && operation) {
            const form = document.createElement('form'); form.method = 'post'; form.className = 'queue-action';
            form.action = `/app/appointments/${visit.id}/${operation}/`;
            [['csrfmiddlewaretoken',token.value],['practice',practice]].forEach(([key,value]) => {
              const field = document.createElement('input'); field.type='hidden'; field.name=key; field.value=value; form.append(field);
            });
            const action = document.createElement('button'); action.className='button';
            action.textContent=operation==='doctor-approve' ? 'Approve & notify patient' : 'Ready now · notify patient';
            form.append(action); queue.append(form);
          }
          const review = document.createElement('button'); review.type='button'; review.className='text-button queue-action';
          review.textContent='Refresh appointment list'; review.addEventListener('click',()=>window.location.reload()); queue.append(review);
        } else {
          const empty=document.createElement('p'); empty.className='muted'; empty.textContent='Reception-approved appointments will appear here in time order.'; queue.append(empty);
        }
      }

      list.replaceChildren();
      if (!data.notifications.length) {
        const empty = document.createElement('p');
        empty.className = 'muted';
        empty.textContent = 'Your personal appointment updates will appear here.';
        list.append(empty);
      }
      data.notifications.forEach(n => {
        const article = document.createElement('article');
        article.className = `notification-item${n.read ? '' : ' unread'}`;
        const title = document.createElement('strong'); title.textContent = n.title;
        const message = document.createElement('p'); message.textContent = n.message;
        const meta = document.createElement('div'); meta.className = 'notification-meta';
        const time = document.createElement('small'); time.textContent = n.time; meta.append(time);
        if (!n.read) {
          const button = document.createElement('button'); button.type = 'button';
          button.className = 'text-button notification-read'; button.dataset.notificationId = n.id;
          button.textContent = 'Mark as read'; meta.append(button);
        }
        article.append(title, message, meta); list.append(article);
      });
    } catch (_) { /* Keep the last displayed updates if the connection drops. */ }
    finally { busy = false; }
  }
  list.addEventListener('click', async event => {
    const button = event.target.closest('.notification-read');
    if (!button) return;
    const token = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (!token) return;
    button.disabled = true;
    try {
      const response = await fetch(`/app/notifications/${button.dataset.notificationId}/read/`, {
        method:'POST', credentials:'same-origin', headers:{'X-CSRFToken':token.value, 'Content-Type':'application/x-www-form-urlencoded'},
        body:`practice=${encodeURIComponent(practice)}`
      });
      if (response.ok) { lastContent = ''; await refreshNotifications(); }
    } catch (_) { /* The user can retry when connected. */ }
    finally { button.disabled = false; }
  });
  refreshNotifications();
  setInterval(refreshNotifications, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshNotifications(); });
}
