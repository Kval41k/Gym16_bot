/* Private notifications, reports and a daily study plan. No inline script handlers. */
const schoolTools = {inbox: [], cursor: null, latest: null, daily: null, reports: [], busy: new Set()};
const schoolSubjects = {math:'Профильная математика', russian:'Русский язык'};
const schoolReasons = {spam:'Спам', abuse:'Оскорбления или травля', unsafe:'Опасный контент', privacy:'Личные данные', other:'Другое'};
const schoolLabels = {schedule:'Расписание', comment:'Комментарий', moderation:'Модерация', news:'Новости', report_result:'Жалоба', general:'Уведомление'};

document.getElementById('header-actions').insertAdjacentHTML('afterbegin', '<button type="button" class="g-btn" data-school-action="inbox" aria-label="Открыть уведомления">🔔 <span class="g-badge" data-inbox-count>0</span></button>');
document.getElementById('ege-materials-list').insertAdjacentHTML('beforebegin', '<section id="school-daily" class="g-card g-stack" aria-live="polite"></section>');
document.getElementById('tab-admin').insertAdjacentHTML('beforeend', `<section id="admin-section-reports" hidden class="g-stack"><div class="g-card g-stack"><h3 class="g-title">Жалобы</h3><p class="g-muted">Проверьте контекст и при необходимости удалите запись через ленту. Рассмотрение жалобы само по себе не удаляет контент.</p><label class="g-label" for="school-report-filter">Статус</label><select id="school-report-filter" class="g-input"><option value="pending">Ожидают рассмотрения</option><option value="handled">Рассмотрены</option><option value="dismissed">Отклонены</option></select><button class="g-btn" data-school-action="reports">Обновить</button></div><div id="school-reports-list" class="g-stack"></div></section>`);
document.body.insertAdjacentHTML('beforeend', `
<dialog id="school-inbox-dialog" class="g-editor school-wide-dialog" aria-labelledby="school-inbox-title"><div class="g-row g-between"><h3 id="school-inbox-title" class="g-title">Уведомления</h3><button type="button" class="g-btn" data-school-close="school-inbox-dialog" aria-label="Закрыть уведомления">✕</button></div><p class="g-muted">Замены, новости, комментарии и результаты модерации сохраняются здесь независимо от доставки в Telegram.</p><div class="g-row"><button class="g-btn" data-school-action="inbox-refresh">Обновить</button><button class="g-btn" id="school-read-all" data-school-action="read-all">Прочитать все</button></div><div id="school-inbox-list" class="g-stack" aria-live="polite"></div><button class="g-btn" id="school-inbox-more" data-school-action="inbox-more" hidden>Показать ещё</button><p id="school-inbox-error" class="g-error" role="alert"></p></dialog>
<dialog id="school-report-dialog" class="g-editor" aria-labelledby="school-report-title"><form id="school-report-form" class="g-stack"><h3 id="school-report-title" class="g-title">Пожаловаться</h3><p class="g-muted">Жалоба доступна только администрации. Запись останется в ленте до решения администратора.</p><label class="g-label" for="school-report-reason">Причина</label><select class="g-input" id="school-report-reason">${Object.entries(schoolReasons).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select><label class="g-label" for="school-report-details">Что произошло?</label><textarea class="g-input" id="school-report-details" maxlength="1000" placeholder="Необязательно, кроме причины «Другое»"></textarea><p id="school-report-error" class="g-error" role="alert"></p><div class="g-row"><button type="button" class="g-btn" data-school-close="school-report-dialog">Отмена</button><button type="submit" class="g-btn primary">Отправить жалобу</button></div></form></dialog>`);

window.communityScheduleChangesHTML = function(data) {
  if (!data.is_override) return '';
  const fields = {subject:'Предмет', cabinet:'Кабинет', teacher_name:'Учитель', note:'Примечание'};
  const time = row => `${row.start_time || '—'}–${row.end_time || '—'}`;
  const items = (data.changes || []).map(change => {
    const row = change.after || change.before;
    const audience = [row.profile_name, row.subgroup ? `Группа ${row.subgroup}` : ''].filter(Boolean).join(' · ');
    const label = `${row.lesson_number} урок${audience ? ' · ' + audience : ' · весь класс'}`;
    let detail;
    if (change.kind === 'cancelled') detail = `<strong>Отменён: ${toolsEsc(row.subject)}</strong><p class="g-muted">${toolsEsc(time(row))}</p>`;
    else if (change.kind === 'added') detail = `<strong>Добавлен: ${toolsEsc(row.subject)}</strong><p class="g-muted">${toolsEsc(time(row))} · каб. ${toolsEsc(row.cabinet || '—')}</p>`;
    else {
      const changed = new Set(change.fields);
      detail = Object.entries(fields).filter(([key]) => changed.has(key)).map(([key,title]) => `<p>${title}: <del>${toolsEsc(change.before[key] || '—')}</del> → <strong>${toolsEsc(change.after[key] || '—')}</strong></p>`).join('');
      if (changed.has('start_time') || changed.has('end_time')) detail += `<p>Время: <del>${toolsEsc(time(change.before))}</del> → <strong>${toolsEsc(time(change.after))}</strong></p>`;
    }
    return `<li class="school-change ${change.kind}"><div class="g-muted">${toolsEsc(label)}</div>${detail}</li>`;
  }).join('');
  return `<section class="g-card school-changes"><h3 class="g-title">Изменения на этот день</h3>${data.note ? `<p>${toolsEsc(data.note)}</p>` : ''}${items ? `<ul>${items}</ul>` : '<p class="g-muted">Состав уроков совпадает с обычным расписанием.</p>'}</section>`;
};

async function schoolLoadInbox(append = false) {
  const ticket = schoolTools.inboxTicket = (schoolTools.inboxTicket || 0) + 1;
  const url = '/api/me/notifications' + (append && schoolTools.cursor ? '?before_id=' + schoolTools.cursor : '');
  const data = await toolsRequest(url);
  if (ticket !== schoolTools.inboxTicket) return;
  schoolTools.inbox = append ? [...schoolTools.inbox, ...data.items] : data.items;
  schoolTools.cursor = data.next_cursor; if (!append) schoolTools.latest = data.latest_id;
  document.querySelectorAll('[data-inbox-count]').forEach(node => node.textContent = data.unread > 99 ? '99+' : data.unread);
  document.querySelector('[data-school-action="inbox"]').setAttribute('aria-label', `Уведомления, непрочитанных: ${data.unread}`);
  document.getElementById('school-read-all').disabled = !data.unread;
  schoolRenderInbox();
}
function schoolRenderInbox() {
  document.getElementById('school-inbox-list').innerHTML = schoolTools.inbox.map(item => `<article class="school-inbox-item ${item.read ? '' : 'unread'}"><div class="g-row g-between"><span class="g-badge">${toolsEsc(schoolLabels[item.kind] || 'Уведомление')}</span><time class="g-muted">${toolsEsc(toolsDate(item.created_at))}</time></div><p>${toolsEsc(item.text)}</p><button class="g-btn" data-school-action="inbox-item" data-school-id="${item.id}">${item.link ? 'Открыть' : item.read ? 'Прочитано' : 'Прочитать'}</button></article>`).join('') || '<p class="g-muted">Здесь появятся ваши уведомления.</p>';
  document.getElementById('school-inbox-more').hidden = !schoolTools.cursor;
}
async function schoolLoadDaily() {
  const node = document.getElementById('school-daily');
  if (!state.user?.id || state.user.access_allowed === false) {node.innerHTML = '';return;}
  const ticket = schoolTools.dailyTicket = (schoolTools.dailyTicket || 0) + 1;
  try {
    const data = await toolsRequest('/api/me/practice/daily');
    if (ticket !== schoolTools.dailyTicket) return;
    schoolTools.daily = data;
    window.schoolToolsDailyStats={completed:data.completed,total:data.items.length,correct:data.correct};
    const done = data.completed, total = data.items.length;
    node.innerHTML = `<div class="g-row g-between"><h3 class="g-title">Мой план на сегодня</h3><span class="g-badge">${done}/${total}</span></div><p class="g-muted">До ${data.target} коротких заданий: новые темы и повторение ошибок. Обновляется ежедневно по времени Тюмени.</p><progress class="school-progress" max="${total || 1}" value="${done}" aria-label="Выполнено заданий"></progress>${total ? `<ul class="school-plan">${data.items.map(item => `<li><span>${item.done ? item.correct ? '✓' : '↻' : item.review ? '↻' : '○'}</span><div>${toolsEsc(schoolSubjects[item.subject_code])} · №${item.task_number}<p class="g-muted">${toolsEsc(item.title)} · ${item.done ? item.correct ? 'Верно' : 'Ошибка сохранена для повторения' : item.review ? 'Повторение ошибки' : 'Новое задание'}</p></div></li>`).join('')}</ul>` : '<p class="g-muted">Все задания решены или ошибки ещё не готовы к повторению.</p>'}<button class="g-btn primary" data-school-action="daily" ${done >= total ? 'disabled' : ''}>${done ? 'Продолжить план' : 'Начать план'}</button><h4 class="g-title">За последние 7 дней</h4><div class="school-week">${data.week.map(day => `<div><span class="g-muted">${toolsEsc(day.date.slice(8) + '.' + day.date.slice(5,7))}</span><strong>${day.correct}/${day.answered}</strong></div>`).join('')}</div><p class="g-muted">Верные ответы / все попытки</p><h4 class="g-title">Темы для повторения</h4>${data.weak_topics.length ? data.weak_topics.map(topic => `<button class="g-btn school-weak" data-school-action="weak" data-subject="${toolsEsc(topic.subject_code)}" data-task="${topic.task_number}">${toolsEsc(schoolSubjects[topic.subject_code])} №${topic.task_number} · ${toolsEsc(topic.title)} · ошибок для разбора: ${topic.remaining}</button>`).join('') : '<p class="g-muted">Пока нет ошибок для повторения. Начните с плана на сегодня.</p>'}`;
  } catch (error) { if (ticket === schoolTools.dailyTicket) node.innerHTML = `<h3 class="g-title">Мой план на сегодня</h3><p class="g-error">${toolsEsc(error.message)}</p><button class="g-btn" data-school-action="daily-refresh">Повторить загрузку</button>`; }
}
window.schoolLoadDaily = schoolLoadDaily;

async function schoolLoadReports(append = false) {
  if (!checkIsAdmin()) return;
  const status = document.getElementById('school-report-filter').value;
  const ticket = schoolTools.reportTicket = (schoolTools.reportTicket || 0) + 1;
  const list = document.getElementById('school-reports-list');
  if (!append) schoolTools.reports = [];
  try {
    const rows = await toolsRequest('/api/admin/reports?' + new URLSearchParams({status, offset:schoolTools.reports.length, limit:30}));
    if (ticket !== schoolTools.reportTicket) return;
    schoolTools.reports.push(...rows);
    list.innerHTML = schoolTools.reports.map(row => `<article class="g-card g-stack"><div class="g-row g-between"><h4 class="g-title">Жалоба №${row.id} · ${row.target_type === 'news' ? 'Новость' : 'Комментарий'}</h4><span class="g-muted">${toolsEsc(toolsDate(row.created_at))}</span></div><strong>${toolsEsc(schoolReasons[row.reason] || row.reason)}</strong><p>${toolsEsc(row.details)}</p><details><summary>Контекст на момент жалобы</summary><h4>${toolsEsc(row.context.title)}</h4><p class="school-context">${toolsEsc(row.context.content)}</p>${row.context.comment ? `<blockquote class="school-context">${toolsEsc(row.context.comment.author_name)}: ${toolsEsc(row.context.comment.text)}</blockquote>` : ''}</details><button class="g-btn" data-school-action="report-post" data-school-id="${row.post_id}">Открыть публикацию</button>${row.status === 'pending' ? `<form class="school-resolution g-stack" data-report-id="${row.id}"><label class="g-label" for="resolution-${row.id}">Результат рассмотрения</label><textarea id="resolution-${row.id}" name="resolution" class="g-input" maxlength="1000" required></textarea><div class="g-row"><button type="submit" class="g-btn primary" name="status" value="handled">Рассмотрена</button><button type="submit" class="g-btn" name="status" value="dismissed">Отклонить</button></div><p class="g-error" role="alert"></p></form>` : `<p>${toolsEsc(row.resolution || '')}</p>`}</article>`).join('') || '<div class="g-card g-muted">Жалоб с этим статусом нет.</div>';
    if (rows.length === 30) list.insertAdjacentHTML('beforeend', '<button class="g-btn" data-school-action="reports-more">Показать ещё</button>');
  } catch (error) { if (ticket === schoolTools.reportTicket) list.innerHTML = `<p class="g-error">${toolsEsc(error.message)}</p>`; }
}
window.schoolLoadReports = schoolLoadReports;
document.getElementById('school-report-filter').addEventListener('change', () => schoolLoadReports());

async function schoolOpenPost(id, comments = false) {
  // Clear an active search so a published post is reachable even after changing filters.
  community.query = ''; community.offset = 0;
  const input = document.getElementById('community-news-search'); if (input) input.value = '';
  switchTab('tab-news');
  await toolsNewsTab('feed');
  const posts = await toolsRequest('/api/news?post_id=' + Number(id));
  if (!posts.length) throw new Error('Публикация удалена или недоступна');
  const post = posts[0];
  if (!state.news.some(row => row.id === post.id)) state.news.unshift(post);
  document.getElementById('news-posts-list').innerHTML = state.news.map(row => renderNewsPost(row)).join('');
  document.querySelector(`[data-report-type="news"][data-report-id="${post.id}"]`)?.closest('article')?.scrollIntoView({block:'center'});
  if (comments) await openCommentsSheet(Number(id));
}

document.addEventListener('click', async event => {
  const close = event.target.closest('[data-school-close]');
  if (close) {document.getElementById(close.dataset.schoolClose)?.close();return;}
  const report = event.target.closest('[data-report-type]');
  if (report) {
    if(document.getElementById('school-report-dialog').open)return;
    schoolTools.target = {target_type:report.dataset.reportType, target_id:Number(report.dataset.reportId)};
    document.getElementById('school-report-form').reset();document.getElementById('school-report-error').textContent = '';
    document.getElementById('school-report-dialog').showModal();return;
  }
  const button = event.target.closest('[data-school-action]');if (!button || button.disabled) return;
  const action = button.dataset.schoolAction;if (schoolTools.busy.has(action)) return;
  schoolTools.busy.add(action);button.disabled = true;
  try {
    document.getElementById('school-inbox-error').textContent = '';
    if (action === 'inbox') {document.getElementById('school-inbox-dialog').showModal();await schoolLoadInbox();}
    if (action === 'inbox-refresh') await schoolLoadInbox();
    if (action === 'inbox-more') await schoolLoadInbox(true);
    if (action === 'read-all' && schoolTools.latest) {await toolsRequest('/api/me/notifications/read','PUT',{through_id:schoolTools.latest});await schoolLoadInbox();}
    if (action === 'inbox-item') {
      const item = schoolTools.inbox.find(row => row.id === Number(button.dataset.schoolId));if (!item) return;
      await toolsRequest(`/api/me/notifications/${item.id}/read`,'PUT');item.read = true;
      if (item.link) {document.getElementById('school-inbox-dialog').close();if (item.link.startsWith('news:')) await schoolOpenPost(item.link.split(':')[1], item.kind === 'comment');else if (['schedule','profile','news'].includes(item.link)) switchTab('tab-' + item.link);}
      await schoolLoadInbox();
    }
    if (action === 'daily-refresh') await schoolLoadDaily();
    if (action === 'daily') {school.practice = {mode:'daily'};document.getElementById('school-practice-dialog').showModal();await schoolNextPractice();}
    if (action === 'weak') {school.practice={subject:button.dataset.subject,number:Number(button.dataset.task),mode:'mistakes'};document.getElementById('school-practice-dialog').showModal();await schoolNextPractice();}
    if (action === 'reports') await schoolLoadReports();
    if (action === 'reports-more') await schoolLoadReports(true);
    if (action === 'report-post') await schoolOpenPost(button.dataset.schoolId,true);
  } catch (error) {if (document.getElementById('school-inbox-dialog').open) document.getElementById('school-inbox-error').textContent = error.message;else toolsToast(error.message);}
  finally {schoolTools.busy.delete(action);button.disabled = false;}
});
document.addEventListener('submit', async event => {
  const form = event.target;
  if (form.id !== 'school-report-form' && !form.matches('.school-resolution')) return;
  event.preventDefault();if (form.dataset.saving) return;
  form.dataset.saving = 'true';const submitter = event.submitter;const status = submitter?.value;
  const buttons = form.querySelectorAll('button');buttons.forEach(button => button.disabled = true);
  const error = form.id === 'school-report-form' ? document.getElementById('school-report-error') : form.querySelector('.g-error');error.textContent = '';
  try {
    if (form.id === 'school-report-form') {await toolsRequest('/api/reports','POST',{...schoolTools.target, reason:document.getElementById('school-report-reason').value, details:document.getElementById('school-report-details').value.trim()});document.getElementById('school-report-dialog').close();toolsToast('Жалоба отправлена администрации');}
    else {await toolsRequest(`/api/admin/reports/${Number(form.dataset.reportId)}/resolve`,'POST',{status,resolution:form.elements.resolution.value.trim()});await schoolLoadReports();}
  } catch (reason) {error.textContent = reason.message;}
  finally {delete form.dataset.saving;buttons.forEach(button => button.disabled = false);}
});
const schoolToolsPersonal = loadPersonalTools;
loadPersonalTools = async function() {await schoolToolsPersonal();if (state.user?.id && state.user.access_allowed !== false) await Promise.allSettled([schoolLoadInbox(), schoolLoadDaily()]);};
window.loadPersonalTools = loadPersonalTools;
