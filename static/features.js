/* Tools share the authenticated Mini App state and existing navigation. */
const toolsState = {mode: 'day', scheduleRequest: 0, personal: {}, progress: {}, egeFilter: 'all', news: 'feed', admin: 'moderation', rows: [], preview: null, logCursor: null};
const toolsDays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];
const toolsBusy = new Set();
const toolsEsc = escapeHtml;

async function toolsRequest(url, method = 'GET', data) {
  const res = await fetch(url, {method, headers: API._getHeaders({'Content-Type': 'application/json'}), body: data === undefined ? undefined : JSON.stringify(data)});
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Ошибка ${res.status}. Проверьте заполнение полей.`);
  }
  return res.json();
}
function toolsToast(message) {
  document.querySelector('.g-toast')?.remove();
  const node = document.createElement('div');
  node.className = 'g-toast'; node.setAttribute('role', 'status'); node.textContent = message;
  document.body.append(node); setTimeout(() => node.remove(), 4500);
}
async function toolsRun(key, action) {
  if (toolsBusy.has(key)) return;
  toolsBusy.add(key);
  const buttons = document.querySelectorAll(`[data-busy="${key}"]`);
  buttons.forEach(button => button.disabled = true);
  try { return await action(); }
  catch (error) { toolsToast(error.message || 'Не удалось выполнить действие'); }
  finally { toolsBusy.delete(key); buttons.forEach(button => button.disabled = false); }
}
function toolsDate(iso) {
  if (!iso) return '';
  return new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z').toLocaleString('ru-RU', {timeZone:'Asia/Yekaterinburg', dateStyle:'short', timeStyle:'short'});
}

// Schedule: day/week modes, familiar class/profile controls, clear current/next lessons.
document.getElementById('live-status-card').insertAdjacentHTML('afterend', `
  <div class="g-row g-between school-schedule-toolbar"><div class="g-tabs" role="group" aria-label="Вид расписания">
  <button class="g-btn primary" id="tools-day" onclick="toolsScheduleMode('day')">День</button>
  <button class="g-btn" id="tools-week" onclick="toolsScheduleMode('week')">Неделя</button></div>
  <button class="g-btn school-schedule-today" onclick="toolsToday()">Сегодня</button></div>
  <div id="tools-schedule-date" class="g-muted"></div>`);
function toolsScheduleMode(mode) { toolsState.mode = mode; loadSchedule(); }
function toolsToday() {
  toolsState.mode = 'day'; const day = getTyumenDate().getDay(); selectDay(day === 0 ? 0 : day - 1);
}
function toolsLessonPhase(slot, day) {
  if (window.communityScheduleDate && window.communityScheduleDate(day) !== window.communityToday()) return '';
  const now = getTyumenDate();
  if (!slot.start_time || !slot.end_time || now.getDay() - 1 !== day) return '';
  const minute = now.getHours() * 60 + now.getMinutes();
  const parse = value => { const [h, m] = (value || '00:00').split(':').map(Number); return h * 60 + m; };
  if (minute >= parse(slot.start_time) && minute < parse(slot.end_time)) return 'current';
  if (slot.start_time && minute < parse(slot.start_time)) return 'future';
  return slot.end_time ? 'past' : '';
}
renderLessonSlot = function(slot, day = state.selectedDay, nextNumber = null) {
  let phase = toolsLessonPhase(slot, day);
  if (phase === 'future') phase = slot.lesson_number === nextNumber ? 'next' : '';
  return `<article class="g-card g-lesson ${phase}"><div class="g-lesson-head"><div class="g-row">
    <span class="g-lesson-number">${slot.lesson_number}</span><b>${slot.start_time ? `${toolsEsc(slot.start_time)} – ${toolsEsc(slot.end_time)}` : slot.lessons.some(item => item.start_time) ? "Время указано у каждого профиля" : "Время уточняется"}</b></div>
    ${phase === 'current' ? '<span class="g-badge approved">Сейчас</span>' : phase === 'next' ? '<span class="g-badge">Следующий</span>' : ''}</div>
    ${slot.lessons.map(lesson => `<div class="g-sublesson"><div class="g-row g-between"><h3 class="g-title">${toolsEsc(lesson.subject)}</h3><span class="g-badge">Каб. ${toolsEsc(lesson.cabinet || '—')}</span></div>
      <div class="g-muted" style="margin-top:7px">${lesson.start_time && (!slot.start_time || lesson.start_time !== slot.start_time || lesson.end_time !== slot.end_time) ? `${toolsEsc(lesson.start_time)}–${toolsEsc(lesson.end_time)} · ` : ""}${toolsEsc(lesson.teacher_name || 'Учитель не указан')}</div>
      ${lesson.profile_name ? `<span class="g-badge">${toolsEsc(lesson.profile_name)}</span>` : ''}
      ${lesson.subgroup ? `<span class="g-badge">Группа ${lesson.subgroup}</span>` : ''}
      ${lesson.note ? `<div class="g-note">${toolsEsc(lesson.note)}</div>` : ''}</div>`).join('')}</article>`;
};
loadSchedule = async function(quiet = false) {
  const requestId = ++toolsState.scheduleRequest;
  const container = document.getElementById('schedule-cards-list');
  const targetClass = state.viewingClass || state.user?.class_name || '11А';
  if (!toolsState.initialProfile && targetClass === state.user?.class_name && state.structure.class_profiles?.[targetClass]?.includes(state.user?.profile_name)) {
    state.selectedProfileFilter = state.user.profile_name;
    toolsState.initialProfile = true;
  }
  renderScheduleProfileFilters();
  document.getElementById('tools-day').classList.toggle('primary', toolsState.mode === 'day');
  document.getElementById('tools-week').classList.toggle('primary', toolsState.mode === 'week');
  document.querySelector('.day-btn')?.parentElement.classList.toggle('hidden', toolsState.mode === 'week');
  document.getElementById('tools-schedule-date').textContent = toolsState.mode === 'week' ? `Неделя · ${targetClass}` : `${toolsDays[state.selectedDay]} · ${targetClass}`;
  if (!quiet) container.innerHTML = '<div class="g-card g-muted">Загрузка расписания…</div>';
  const profile = state.selectedProfileFilter || 'all';
  const days = toolsState.mode === 'week' ? [0,1,2,3,4,5] : [state.selectedDay];
  try {
    const results = await Promise.all(days.map(day => {
      const params = new URLSearchParams({class_name: targetClass, day_of_week: Math.min(day,5), only_my_profile: profile !== 'all', profile_name: profile === 'all' ? '' : profile});
      const date = window.communityScheduleDate?.(day);
      if (date) params.set('date', date);
      if (window.schoolViewingGroup?.()) params.set('subgroup', window.schoolViewingGroup());
      return toolsRequest('/api/schedule/lessons?' + params);
    }));
    if (requestId !== toolsState.scheduleRequest) return;
    if (results[0]?.schedule_loaded === false) {
      container.innerHTML = `<div class="g-card" style="text-align:center;padding:36px 20px"><div style="font-size:28px">📚</div><h3 class="g-title">Расписание ещё не загружено</h3><p class="g-muted">Для ${toolsEsc(targetClass)} класса расписание ещё не добавлено.</p></div>`;
      return;
    }
    container.innerHTML = results.map((data, index) => {
      const day = days[index];
      if (data.date === window.communityToday?.() || (!data.date && getTyumenDate().getDay() - 1 === day)) state.todayLessons = data.slots;
      const next = data.slots.find(slot => toolsLessonPhase(slot, day) === 'future');
      const lessonTimes = data.slots.flatMap(slot => slot.lessons).filter(item => item.start_time && item.end_time);
      const firstTime = lessonTimes.map(item => item.start_time).sort()[0] || '';
      const lastTime = lessonTimes.map(item => item.end_time).sort().at(-1) || '';
      const cards = data.slots.map(slot => renderLessonSlot(slot, day, next?.lesson_number)).join('') || '<div class="g-card g-muted">Уроков в расписании нет.</div>';
      const note = data.is_override ? `<div class="g-note">${toolsEsc(data.note || (data.slots.length ? 'Замены на эту дату' : 'Занятия отменены'))}</div>` : '';
      if (toolsState.mode === 'day') return note + cards;
      return `<details class="g-week-day" ${getTyumenDate().getDay() - 1 === day ? 'open' : ''}><summary>${toolsDays[day]} <span class="g-muted">· ${data.slots.length} ур. ${data.slots.length ? `· ${toolsEsc(firstTime)}–${toolsEsc(lastTime)}` : ''}</span></summary><div>${note}${cards}</div></details>`;
    }).join('');
    window.communityDateLabel?.();
    calculateLiveStatusLocally();
    updateLiveScheduleStatus().catch(() => {});
  } catch (error) {
    if (requestId === toolsState.scheduleRequest) container.innerHTML = `<div class="g-card g-muted">${toolsEsc(error.message)} <button class="g-btn" onclick="loadSchedule()">Повторить</button></div>`;
  }
};

// Saved personal settings and progress live on the server, across devices.
document.getElementById('edit-profile-btn').insertAdjacentHTML('afterend', `
  <section class="g-card g-stack"><h3 class="g-title">Оформление</h3>
    <p class="g-muted">Режим «Как в Telegram» автоматически меняет тему вместе с Telegram.</p>
    <div class="g-theme-options" role="group" aria-label="Тема приложения">
      <button type="button" class="g-btn" data-busy="theme" data-theme-choice="auto" onclick="toolsChooseTheme('auto')">Как в Telegram</button>
      <button type="button" class="g-btn" data-busy="theme" data-theme-choice="light" onclick="toolsChooseTheme('light')">☀ Светлая</button>
      <button type="button" class="g-btn" data-busy="theme" data-theme-choice="dark" onclick="toolsChooseTheme('dark')">☾ Тёмная</button>
    </div></section>
  <section class="g-card g-stack"><h3 class="g-title">Уведомления в Telegram</h3>
    <p class="g-muted">Включи нужные уведомления и открой чат бота командой /start. Время — Тюмень (UTC+5).</p>
    <label class="g-row"><input type="checkbox" id="tools-reminders"> Перед началом урока</label>
    <div class="g-reminder-control"><div class="g-row g-between"><label for="tools-reminder-minutes" class="g-muted">Напомнить до начала</label><output id="school-reminder-value" for="tools-reminder-minutes">За 10 минут</output></div>
    <input id="tools-reminder-minutes" class="g-reminder-range" type="range" min="5" max="15" step="5" value="10" aria-label="За сколько минут до урока напоминать" aria-valuetext="За 10 минут" oninput="schoolReminderPreview()">
    <div class="g-reminder-ticks">${[5,10,15].map(n=>`<button type="button" data-reminder-minutes="${n}" onclick="schoolChooseReminder(${n})">${n} мин</button>`).join('')}</div></div>
    <label class="g-row"><input type="checkbox" id="tools-changes"> При изменении расписания моего класса</label>
    <button class="g-btn primary" data-busy="prefs" onclick="toolsSavePreferences()">Сохранить настройки</button>
    <div class="g-muted">Доставка напоминаний зависит от доступности сервера. На бесплатном хостинге во время сна сервиса они не отправляются.</div>
  </section>`);
async function loadPersonalTools() {
  if (!window.Telegram?.WebApp?.initData || !state.user?.id) return;
  try {
    const [prefs, progress] = await Promise.all([toolsRequest('/api/me/preferences'), toolsRequest('/api/me/materials')]);
    toolsState.personal = prefs; toolsState.progress = progress;
    if (!toolsBusy.has('theme')) window.GymTheme?.setMode(prefs.theme || 'auto');
    document.getElementById('tools-reminders').checked = prefs.lesson_reminders;
    document.getElementById('tools-changes').checked = prefs.schedule_changes;
    document.getElementById('tools-reminder-minutes').value = prefs.reminder_minutes;
    window.schoolReminderPreview?.();
    toolsRenderEge();
  } catch (error) { console.warn('Personal tools unavailable:', error.message); }
}
window.loadPersonalTools = loadPersonalTools;
function toolsThemeButtons() {
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === window.GymTheme?.getMode()));
  });
}
window.addEventListener('gym16-theme-applied', toolsThemeButtons);
toolsThemeButtons();
async function toolsChooseTheme(mode) {
  return toolsRun('theme', async () => {
    const previous = window.GymTheme.getMode();
    window.GymTheme.setMode(mode);
    try {
      const prefs = await toolsRequest('/api/me/preferences', 'PUT', {theme: mode});
      toolsState.personal = prefs;
      toolsToast('Тема сохранена');
    } catch (error) {
      window.GymTheme.setMode(previous);
      throw error;
    }
  });
}
async function toolsSavePreferences() {
  return toolsRun('prefs', async () => {
    toolsState.personal = await toolsRequest('/api/me/preferences', 'PUT', {
      lesson_reminders: document.getElementById('tools-reminders').checked,
      reminder_minutes: Number(document.getElementById('tools-reminder-minutes').value),
      schedule_changes: document.getElementById('tools-changes').checked
    });
    toolsToast('Настройки уведомлений сохранены');
  });
}

// News status is visible only to the authenticated author.
document.getElementById('news-posts-list').insertAdjacentHTML('beforebegin', `<div class="g-tabs">
  <button class="g-btn primary" id="tools-feed-btn" onclick="toolsNewsTab('feed')">Лента</button>
  <button class="g-btn" id="tools-mine-btn" onclick="toolsNewsTab('mine')">Мои предложения</button></div><div id="tools-my-news" hidden></div>`);
async function toolsNewsTab(tab) {
  toolsState.news = tab;
  document.getElementById('news-posts-list').hidden = tab !== 'feed';
  document.getElementById('tools-my-news').hidden = tab !== 'mine';
  document.getElementById('tools-feed-btn').classList.toggle('primary', tab === 'feed');
  document.getElementById('tools-mine-btn').classList.toggle('primary', tab === 'mine');
  if (tab === 'mine') await toolsMyNews();
}
async function toolsMyNews() {
  const list = document.getElementById('tools-my-news');
  list.innerHTML = '<div class="g-card g-muted">Загрузка предложений…</div>';
  await toolsRun('my-news', async () => {
    const posts = await toolsRequest('/api/me/news');
    const names = {pending:'На модерации', approved:'Опубликовано', rejected:'Отклонено'};
    list.innerHTML = posts.map(post => `<article class="g-card g-stack"><div class="g-row g-between"><span class="g-badge ${post.status}">${names[post.status] || toolsEsc(post.status)}</span><time class="g-muted">${toolsDate(post.created_at)}</time></div>
      <h3 class="g-title">${toolsEsc(post.title)}</h3>${post.reason ? `<div class="g-note">Причина: ${toolsEsc(post.reason)}</div>` : ''}</article>`).join('') || '<div class="g-card g-muted">Пока нет предложенных новостей. Отправь первую через кнопку «Предложить».</div>';
  });
}
const toolsOriginalNews = renderNewsPost;
renderNewsPost = function(post) {
  return toolsOriginalNews(post).replace(`<div class="text-[10px] text-ios-secondaryText">${toolsEsc(post.created_at)}</div>`, `<time>${toolsEsc(post.created_at)}</time>`)
    .replace('<!-- Post Content -->', `${checkCanEdit() ? `<button class="g-btn" onclick="openEditModal(${post.id})">✎ Редактировать</button>` : ''}<!-- Post Content -->`);
};
handleModeratePost = async function(postId, action) {
  let reason = null;
  if (action === 'reject') {
    reason = prompt('Причина отклонения (будет видна автору). Можно оставить пустой:', '');
    if (reason === null) return;
  }
  await toolsRun('moderate-' + postId, async () => {
    await toolsRequest(`/api/admin/news/${postId}/moderate`, 'POST', {action, reason, admin_id: state.user.id});
    await Promise.all([loadAdminPendingNews(), checkPendingNewsCount(), loadNews()]);
    toolsToast(action === 'approve' ? 'Новость опубликована' : 'Новость отклонена');
  });
};
const toolsOriginalReaction = togglePostReaction;
togglePostReaction = (id, emoji) => toolsRun('reaction-' + id, () => toolsOriginalReaction(id, emoji));

// In-app image viewer with zoom and scrolling.
document.body.insertAdjacentHTML('beforeend', `<dialog class="g-viewer" id="tools-image-viewer" aria-label="Просмотр фотографии">
  <div class="g-viewer-toolbar"><button onclick="toolsZoom(-.5)" aria-label="Уменьшить">−</button><span id="tools-zoom-label">100%</span><button onclick="toolsZoom(.5)" aria-label="Увеличить">+</button><button onclick="document.getElementById('tools-image-viewer').close()">Закрыть</button></div>
  <div class="g-viewer-body"><img id="tools-viewer-image" alt="Фотография крупным планом"></div></dialog>`);
let toolsZoomLevel = 1;
function toolsZoom(delta) {
  toolsZoomLevel = Math.max(1, Math.min(4, toolsZoomLevel + delta));
  document.getElementById('tools-viewer-image').style.width = `${toolsZoomLevel * 100}%`;
  document.getElementById('tools-zoom-label').textContent = `${Math.round(toolsZoomLevel * 100)}%`;
}
document.addEventListener('click', event => {
  const image = event.target.closest('.safe-image-open');
  if (!image) return;
  const url = safeImageUrl(image.dataset.imageUrl);
  if (!url) return;
  event.preventDefault(); event.stopImmediatePropagation();
  window.setProtectedImage(document.getElementById('tools-viewer-image'), url);
  toolsZoomLevel = 1; toolsZoom(0);
  document.getElementById('tools-image-viewer').showModal();
}, true);

// EGE: local full-text filtering on the fetched subject, saved and studied materials.
document.getElementById('ege-materials-list').insertAdjacentHTML('beforebegin', `<section class="g-stack">
  <input class="g-input" type="search" id="tools-ege-search" placeholder="Поиск по теме, тексту или № задания" aria-label="Поиск материалов" oninput="toolsRenderEge()">
  <div class="g-tabs"><button class="g-btn primary" id="tools-ege-all" onclick="toolsEgeFilter('all')">Все материалы</button><button class="g-btn" id="tools-ege-saved" onclick="toolsEgeFilter('saved')">Закладки</button><button class="g-btn" id="tools-ege-studied" onclick="toolsEgeFilter('studied')">Изучено</button></div>
  <div class="g-muted" id="tools-ege-progress"></div></section>`);
const toolsOriginalEgeRender = renderEgeMaterials;
const toolsOriginalEgeCard = renderSingleEgeMaterialCard;
let toolsEgeFetch = 0;
loadEgeMaterials = async function() {
  const requestId = ++toolsEgeFetch;
  const list = document.getElementById('ege-materials-list');
  list.innerHTML = '<div class="g-card g-muted">Загрузка материалов…</div>';
  renderEgeTaskPills();
  try {
    const materials = await toolsRequest('/api/ege/materials?' + new URLSearchParams({subject_code: state.ege.activeSubject || 'russian'}));
    if (requestId !== toolsEgeFetch) return;
    state.ege.materials = materials; toolsRenderEge();
  } catch (error) { if (requestId === toolsEgeFetch) list.innerHTML = `<div class="g-card g-muted">${toolsEsc(error.message)}</div>`; }
};
function toolsEgeFilter(value) { toolsState.egeFilter = value; toolsRenderEge(); }
function toolsRenderEge() {
  if (!state.ege) return;
  const all = state.ege.materials || [];
  const query = document.getElementById('tools-ege-search').value.trim().toLocaleLowerCase('ru');
  const filtered = all.filter(item => {
    const progress = toolsState.progress[item.id] || {};
    const topic = FIPI_TOPICS[state.ege.activeSubject]?.[item.task_number] || '';
    return (!state.ege.selectedTask || item.task_number === state.ege.selectedTask)
      && (!query || `${item.title} ${item.theory} ${item.task_number} ${topic}`.toLocaleLowerCase('ru').includes(query))
      && (toolsState.egeFilter === 'all' || (toolsState.egeFilter === 'saved' ? progress.bookmarked : progress.studied));
  });
  ['all','saved','studied'].forEach(value => document.getElementById('tools-ege-' + value).classList.toggle('primary', value === toolsState.egeFilter));
  const studied = all.filter(item => toolsState.progress[item.id]?.studied).length;
  document.getElementById('tools-ege-progress').textContent = `Изучено ${studied} из ${all.length} материалов · найдено ${filtered.length}`;
  if ((query || toolsState.egeFilter !== 'all') && !filtered.length) {
    document.getElementById('ege-materials-list').innerHTML = '<div class="g-card g-muted">Подходящих материалов нет. Попробуй другой запрос или добавь материал в закладки.</div>';
  } else toolsOriginalEgeRender(filtered);
}
renderSingleEgeMaterialCard = function(material, isAdmin) {
  const progress = toolsState.progress[material.id] || {};
  return toolsOriginalEgeCard(material, isAdmin).replace('</article>', `<div class="g-row" style="padding-top:10px"><button class="g-btn ${progress.bookmarked ? 'primary' : ''}" data-busy="material-${material.id}" aria-pressed="${!!progress.bookmarked}" onclick="toolsMaterial(${material.id},'bookmarked')">${progress.bookmarked ? '★ В закладках' : '☆ Сохранить'}</button>
    <button class="g-btn ${progress.studied ? 'primary' : ''}" data-busy="material-${material.id}" aria-pressed="${!!progress.studied}" onclick="toolsMaterial(${material.id},'studied')">${progress.studied ? '✓ Изучено' : 'Отметить изученным'}</button></div></article>`);
};
function toolsMaterial(id, field) {
  return toolsRun('material-' + id, async () => {
    toolsState.progress[id] = await toolsRequest('/api/me/materials/' + id, 'PUT', {[field]: !toolsState.progress[id]?.[field]});
    toolsRenderEge();
  });
}

// Only the author can edit a comment; the server checks ownership and revision.
document.body.insertAdjacentHTML('beforeend', `<dialog class="g-editor" id="tools-comment-editor" aria-labelledby="tools-comment-editor-title">
  <form onsubmit="toolsSaveComment(event)" class="g-stack"><h3 class="g-title" id="tools-comment-editor-title">Изменить комментарий</h3>
  <label class="g-label" for="tools-comment-text">Текст комментария</label>
  <textarea class="g-input" id="tools-comment-text" maxlength="1000" required></textarea>
  <p class="g-error" id="tools-comment-error" role="alert"></p>
  <div class="g-row" style="justify-content:flex-end"><button type="button" class="g-btn" onclick="document.getElementById('tools-comment-editor').close()">Отмена</button>
    <button type="submit" class="g-btn primary" data-busy="comment-edit">Сохранить</button></div></form></dialog>`);
async function toolsEditComment(id) {
  return toolsRun('comment-open', async () => {
    const comment = await toolsRequest('/api/news/comments/' + id);
    if (Number(comment.user_id) !== Number(state.user.id)) throw new Error('Можно изменять только свои комментарии');
    toolsState.commentEdit = comment;
    document.getElementById('tools-comment-text').value = comment.text;
    document.getElementById('tools-comment-error').textContent = '';
    document.getElementById('tools-comment-editor').showModal();
    document.getElementById('tools-comment-text').focus();
  });
}
async function toolsSaveComment(event) {
  event.preventDefault();
  return toolsRun('comment-edit', async () => {
    const original = toolsState.commentEdit;
    if (!original) return;
    const text = document.getElementById('tools-comment-text').value.trim();
    const errorElement = document.getElementById('tools-comment-error');
    if (!text) { errorElement.textContent = 'Введите текст комментария'; return; }
    try {
      const comment = await toolsRequest('/api/news/comments/' + original.id, 'PUT', {text, revision: original.revision});
      if (state.activePostForComments === original.post_id) {
        renderCommentsList((state.commentsLoaded || []).map(item => item.id === comment.id ? comment : item), state.commentsHasMore);
      }
      document.getElementById('tools-comment-editor').close();
      toolsToast('Комментарий изменён');
    } catch (error) { errorElement.textContent = error.message; }
  });
}

// Admin sections share one navigation and one instance of each panel.
const toolsAdminTabs = document.getElementById('admin-subtab-moderation-btn').parentElement;
toolsAdminTabs.className = 'g-tabs';
toolsAdminTabs.innerHTML = [['moderation','Модерация'],['users','Пользователи'],['schedule','Расписание'],['logs','Логи'],['data','Данные'],['access','Приглашения']]
  .map(([id, label]) => `<button class="g-btn ${id === 'moderation' ? 'primary' : ''}" id="admin-subtab-${id}-btn" onclick="setAdminSubtab('${id}')">${label}${id === 'moderation' ? ' <span id="admin-subtab-pending-badge" class="hidden"></span>' : ''}</button>`).join('');
document.getElementById('tab-admin').insertAdjacentHTML('beforeend', `
  <section id="admin-section-schedule" hidden class="g-stack"><div class="g-card g-stack">
    <h3 class="g-title">Редактор расписания</h3><p class="g-muted">Выберите класс. Изменения относятся ко всей его неделе. Перед публикацией доступен предпросмотр; уроки остальных классов сохраняются.</p>
    <select class="g-input" id="tools-schedule-class" onchange="toolsAdminSchedule()"></select><div class="g-row" id="tools-class-status"></div>
    <div class="g-row"><button class="g-btn" onclick="toolsAddLesson()">+ Урок</button><button class="g-btn" onclick="toolsScheduleCSV()">Вставить CSV</button><button class="g-btn" onclick="toolsDownloadSchedule()">Скачать CSV</button></div>
    <div id="tools-csv-import" hidden><label class="g-label">CSV из таблицы (UTF-8)</label><input class="g-input" type="file" accept=".csv,text/csv" onchange="toolsReadCSV(this)">
      <textarea class="g-input" id="tools-csv-text" rows="6" placeholder="день;урок;предмет;учитель;кабинет;профиль;группа;начало;конец;примечание"></textarea>
      <p class="g-muted">День: Пн–Сб или 0–5. Пустой профиль — весь класс. Начало и конец можно указать в формате ЧЧ:ММ. Поля с разделителем заключайте в кавычки.</p>
      <button class="g-btn" data-busy="schedule-preview" onclick="toolsPreviewSchedule(true)">Проверить CSV</button></div>
    <div id="tools-schedule-grid"></div><button class="g-btn primary" data-busy="schedule-preview" onclick="toolsPreviewSchedule(false)">Предпросмотр изменений</button>
    <div id="tools-schedule-preview" hidden></div></div></section>
  <section id="admin-section-logs" hidden class="g-stack"><div class="g-card g-stack"><h3 class="g-title">Журнал действий</h3>
    <p class="g-muted">Кто, когда и что изменил в приложении или боте. История собирается с момента установки обновления.</p>
    <input class="g-input" id="tools-log-search" placeholder="Имя, @username, Telegram ID или ID записи" oninput="toolsLogSearch()">
    <div class="g-search-controls"><select class="g-input" id="tools-log-section" onchange="toolsLoadLogs()"><option value="">Все разделы</option><option value="profile">Профиль и настройки</option><option value="schedule">Расписание</option><option value="news">Новости</option><option value="comments">Комментарии</option><option value="reactions">Реакции</option><option value="ege">ЕГЭ</option></select>
    <select class="g-input" id="tools-log-action" onchange="toolsLoadLogs()"><option value="">Все действия</option><option value="create">Добавления</option><option value="update">Изменения</option><option value="delete">Удаления</option></select>
    <label class="g-muted">С даты<input class="g-input" type="date" id="tools-log-from" onchange="toolsLoadLogs()"></label><label class="g-muted">По дату<input class="g-input" type="date" id="tools-log-to" onchange="toolsLoadLogs()"></label></div>
    <button class="g-btn" onclick="toolsLoadLogs()">Обновить журнал</button></div><div id="tools-logs-list"></div><button class="g-btn" id="tools-logs-more" data-busy="logs" onclick="toolsLoadLogs(true)" hidden>Показать ещё</button></section>
  <section id="admin-section-data" hidden class="g-stack"><div class="g-card g-stack"><h3 class="g-title">Данные и резервные копии</h3><div id="tools-storage-status" class="g-muted"></div>
    <button class="g-btn primary" data-busy="backup" onclick="toolsBackup()">Скачать резервную копию ZIP</button>
    <p class="g-muted">В архиве — база, журнал действий, настройки и загруженные файлы. Сохраните его в надёжном месте: он содержит данные пользователей.</p>
    <p class="g-muted">Автоматически создаётся одна локальная копия в день, хранятся последние 7. При остановленном сервере новые копии не создаются.</p></div></section>`);
setAdminSubtab = function(tab) {
  if (!checkIsAdmin() && tab !== 'moderation') tab = 'moderation';
  toolsState.admin = tab;
  ['moderation','users','schedule','logs','data','access'].forEach(id => {
    const section = document.getElementById('admin-section-' + id);
    section.hidden = id !== tab; section.classList.toggle('hidden', id !== tab);
    document.getElementById('admin-subtab-' + id + '-btn').classList.toggle('primary', id === tab);
  });
  if (tab === 'moderation') loadAdminPendingNews();
  if (tab === 'users') loadAdminUsers();
  if (tab === 'schedule') toolsAdminSchedule();
  if (tab === 'logs') toolsLoadLogs();
  if (tab === 'data') toolsStorage();
  if (tab === 'access') communityLoadAccess();
};
const toolsSwitchTab = switchTab;
switchTab = function(tab) {
  toolsSwitchTab(tab);
  if (tab === 'tab-admin') setAdminSubtab(toolsState.admin);
  if (tab === 'tab-profile') loadPersonalTools();
  if (tab === 'tab-news' && toolsState.news === 'mine') toolsMyNews();
  if (tab === 'tab-ege') loadPersonalTools();
};

// Editable schedule grid. Preview includes a revision token to detect concurrent edits.
function toolsChosenClass() { return document.getElementById('tools-schedule-class').value || '11А'; }
let toolsAdminScheduleRequest = 0;
async function toolsAdminSchedule() {
  const select = document.getElementById('tools-schedule-class');
  if (!select.options.length) select.innerHTML = (state.structure.classes || ['11А','11Б','11В','11Г','11Д','11Ж']).map(name => `<option>${toolsEsc(name)}</option>`).join('');
  const className = select.value;
  const requestId = ++toolsAdminScheduleRequest;
  toolsState.editClass = null; toolsInvalidatePreview();
  document.getElementById('tools-schedule-grid').innerHTML = '<p class="g-muted">Загрузка расписания…</p>';
  try {
    const data = await toolsRequest('/api/admin/schedule?' + new URLSearchParams({class_name: className}));
    if (requestId !== toolsAdminScheduleRequest) return;
    toolsState.rows = data.rows; toolsState.baseRevision = data.base_revision; toolsState.preview = null;
    toolsState.editClass = className;
    document.getElementById('tools-schedule-preview').hidden = true;
    document.getElementById('tools-class-status').innerHTML = data.classes.map(item => `<span class="g-badge ${item.loaded ? 'approved' : 'pending'}">${toolsEsc(item.name)} · ${item.loaded ? 'загружено' : 'нет расписания'}</span>`).join('');
    toolsRenderScheduleGrid();
  } catch(error) { if (requestId === toolsAdminScheduleRequest) toolsToast(error.message); }
}
function toolsInvalidatePreview() { toolsState.preview = null; document.getElementById('tools-schedule-preview').hidden = true; }
function toolsRenderScheduleGrid() {
  const columns = [['day_of_week','День'],['lesson_number','Урок'],['subject','Предмет'],['teacher_name','Учитель'],['cabinet','Кабинет'],['profile_name','Профиль'],['subgroup','Группа'],['start_time','Начало'],['end_time','Конец'],['note','Примечание']];
  const profiles = state.structure.class_profiles?.[toolsChosenClass()] || [];
  document.getElementById('tools-schedule-grid').innerHTML = `<div class="g-table-wrap"><table class="g-table"><thead><tr>${columns.map(([,title])=>`<th>${title}</th>`).join('')}<th></th></tr></thead><tbody>${toolsState.rows.map((row,index)=>`<tr>${columns.map(([field,title])=>{
    const attrs = `class="g-input ${field === 'subject' ? 'g-subject' : ''}" aria-label="${title}, строка ${index+1}" onchange="toolsEditLesson(${index},'${field}',this.value)"`;
    if (field === 'day_of_week') return `<td><select ${attrs}>${toolsDays.map((day,i)=>`<option value="${i}" ${row[field]===i?'selected':''}>${['Пн','Вт','Ср','Чт','Пт','Сб'][i]}</option>`).join('')}</select></td>`;
    if (field === 'profile_name') return `<td><select ${attrs}><option value="">Весь класс</option>${profiles.map(profile=>`<option ${row[field]===profile?'selected':''}>${toolsEsc(profile)}</option>`).join('')}</select></td>`;
    return `<td><input ${attrs} value="${toolsEsc(row[field]??'')}" ${['lesson_number','subgroup'].includes(field)?'type="number" min="0" max="12"':['start_time','end_time'].includes(field)?'type="time"':''}></td>`;
  }).join('')}<td><button class="g-btn danger" onclick="toolsRemoveLesson(${index})" aria-label="Удалить строку ${index+1}">×</button></td></tr>`).join('')}</tbody></table></div><p class="g-muted">${toolsState.rows.length} строк · таблицу можно прокручивать по горизонтали. Примечания отображаются ученикам в карточках.</p>`;
}
function toolsEditLesson(index, field, value) {
  if (['day_of_week','lesson_number','subgroup'].includes(field)) value = value === '' ? null : Number(value);
  if (['profile_name','note','start_time','end_time'].includes(field) && value === '') value = null;
  toolsState.rows[index][field] = value; toolsInvalidatePreview();
}
function toolsAddLesson() {
  if (!toolsState.editClass) return toolsToast('Дождитесь загрузки класса');
  toolsState.rows.push({day_of_week:0,lesson_number:1,subject:'',teacher_name:'',cabinet:'',profile_name:null,subgroup:null,note:null});
  toolsInvalidatePreview(); toolsRenderScheduleGrid();
}
function toolsRemoveLesson(index) { toolsState.rows.splice(index,1); toolsInvalidatePreview(); toolsRenderScheduleGrid(); }
function toolsScheduleCSV() { const node=document.getElementById('tools-csv-import');node.hidden=!node.hidden; }
async function toolsReadCSV(input) {
  if (input.files[0]) document.getElementById('tools-csv-text').value = await input.files[0].text();
}
function toolsSchedulePayload() { return {class_name:toolsState.editClass || toolsChosenClass(),rows:toolsState.rows,base_revision:toolsState.baseRevision}; }
async function toolsPreviewSchedule(fromCSV) {
  return toolsRun('schedule-preview', async () => {
    if (!toolsState.editClass) throw new Error('Дождитесь загрузки класса.');
    const payload = toolsSchedulePayload();
    if (toolsChosenClass() !== payload.class_name) throw new Error('Дождитесь загрузки выбранного класса.');
    if (fromCSV) { payload.csv_text = document.getElementById('tools-csv-text').value; payload.rows=[]; }
    const preview = await toolsRequest('/api/admin/schedule/preview','POST',payload);
    // Preview must refer to the data originally loaded in this editor.
    if (preview.base_revision !== toolsState.baseRevision) throw new Error('Расписание уже изменено. Выберите класс заново и повторите редактирование.');
    toolsState.rows = preview.rows; toolsState.preview = {class_name:payload.class_name,rows:structuredClone(preview.rows),base_revision:preview.base_revision};
    toolsRenderScheduleGrid();
    const panel = document.getElementById('tools-schedule-preview'); panel.hidden=false;
    panel.innerHTML = `<div class="g-note g-stack"><b>Предпросмотр · ${toolsEsc(payload.class_name)}</b><p>Было ${preview.old_count} строк → станет ${preview.new_count}.</p><p>Без занятий: ${preview.empty_days.map(day=>toolsDays[day]).join(', ')||'нет'}.</p><p>Новая неделя полностью заменит текущее расписание выбранного класса. Подписанные ученики получат уведомление.</p>
      ${preview.new_count === 0 ? '<p><b>Все уроки этого класса будут удалены.</b></p>' : ''}<button class="g-btn primary" data-busy="schedule-publish" onclick="toolsPublishSchedule()">Опубликовать это расписание</button></div>`;
    panel.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
}
async function toolsPublishSchedule() {
  return toolsRun('schedule-publish', async () => {
    if (!toolsState.preview) throw new Error('Сначала сформируйте предпросмотр.');
    if (!confirm(`Опубликовать расписание ${toolsState.preview.class_name}?`)) return;
    const result = await toolsRequest('/api/admin/schedule/publish','POST',toolsState.preview);
    toolsToast(result.changed ? 'Расписание опубликовано' : 'Расписание уже соответствует этим данным');
    await toolsAdminSchedule(); await loadSchedule(); await updateLiveScheduleStatus();
  });
}
function toolsSaveBlob(blob, name) {
  const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
function toolsDownloadSchedule() {
  const fields=['day_of_week','lesson_number','subject','teacher_name','cabinet','profile_name','subgroup','note','start_time','end_time'];
  const quote = value => '"'+String(value??'').replaceAll('"','""')+'"';
  const content='\uFEFF'+fields.join(';')+'\n'+toolsState.rows.map(row=>fields.map(field=>quote(row[field])).join(';')).join('\n');
  toolsSaveBlob(new Blob([content],{type:'text/csv;charset=utf-8'}),`schedule-${toolsChosenClass()}.csv`);
}

// Audit history: filters and cursor pagination keep the page responsive.
const toolsLogSections={profile:'Профиль',schedule:'Расписание',news:'Новости',comments:'Комментарии',reactions:'Реакции',ege:'ЕГЭ'};
const toolsEntities={users:'Пользователь',user_preferences:'Настройки уведомлений',lessons:'Урок',bell_schedules:'Звонки',news_posts:'Новость',news_reviews:'Решение модератора',comments:'Комментарий',reactions:'Реакция',ege_materials:'Материал',material_progress:'Закладки и прогресс'};
const toolsLogFields={id:'ID',user_id:'Пользователь',post_id:'Новость',first_name:'Имя',last_name:'Фамилия',username:'Telegram',class_name:'Класс',profile_name:'Профиль',subgroup:'Группа',is_admin:'Администратор',is_banned:'Блокировка',title:'Заголовок',content:'Текст',text:'Текст',emoji:'Реакция',status:'Статус',reason:'Причина',subject:'Предмет',teacher_name:'Учитель',cabinet:'Кабинет',day_of_week:'День недели',lesson_number:'Номер урока',note:'Примечание',start_time:'Начало занятия',end_time:'Конец занятия',bookmarked:'В закладках',studied:'Изучено',lesson_reminders:'Напоминания об уроках',schedule_changes:'Изменения расписания',reminder_minutes:'За сколько минут',theory:'Теория',task_number:'Номер задания',subject_code:'Предмет ЕГЭ',material_id:'Материал',author_name:'Автор',author_id:'ID автора',author_class:'Класс автора',is_anonymous:'Анонимность',image_url:'Изображение',link_url:'Ссылка',published_at:'Дата публикации'};
let toolsLogTimer, toolsLogRequest=0;
function toolsLogSearch() { clearTimeout(toolsLogTimer);toolsLogTimer=setTimeout(()=>toolsLoadLogs(),350); }
async function toolsLoadLogs(more=false) {
  const requestId=++toolsLogRequest;
  const list=document.getElementById('tools-logs-list');
  if(!more) { list.innerHTML='<div class="g-card g-muted">Загрузка журнала…</div>';toolsState.logCursor=null; }
  const params=new URLSearchParams({q:document.getElementById('tools-log-search').value.replace(/^@/,''),limit:40});
  const section=document.getElementById('tools-log-section').value,action=document.getElementById('tools-log-action').value;
  if(section)params.set('section',section);if(action)params.set('action',action);
  if(more&&toolsState.logCursor)params.set('before_id',toolsState.logCursor);
  const from=document.getElementById('tools-log-from').value,to=document.getElementById('tools-log-to').value;
  if(from)params.set('date_from',from+'T00:00:00+05:00');if(to)params.set('date_to',to+'T23:59:59+05:00');
  try {
    const data=await toolsRequest('/api/admin/logs?'+params);
    if(requestId!==toolsLogRequest)return;
    const labels={create:'Добавлено',update:'Изменено',delete:'Удалено'};
    const value = item => item===null||item===undefined?'—':item===true?'Да':item===false?'Нет':toolsEsc(String(item));
    const html=data.items.map(log=>`<article class="g-card"><div class="g-row g-between"><span class="g-badge">${toolsLogSections[log.section]||toolsEsc(log.section)}</span><time class="g-muted">${toolsDate(log.created_at)}</time></div>
      <h4 class="g-title" style="margin-top:10px">${toolsEsc(log.actor_name)}</h4><div class="g-muted">${log.actor_username?'@'+toolsEsc(log.actor_username)+' · ':''}ID ${log.actor_id} · ${log.source==='bot'?'Telegram-бот':log.source==='calendar'?'Синхронизация календаря':'Приложение'}</div>
      <p style="font-size:13px;margin-top:8px">${labels[log.action]||toolsEsc(log.action)} · ${toolsEntities[log.entity]||toolsEsc(log.entity)} #${toolsEsc(log.entity_id)}</p>
      <details class="g-detail"><summary>Подробности изменения</summary>${Object.entries(log.details).map(([field,change])=>`<div class="g-change"><b>${toolsLogFields[field]||toolsEsc(field)}</b><br>${log.action==='update'&&change&&typeof change==='object'?`<del>${value(change.before)}</del> → <ins>${value(change.after)}</ins>`:value(change)}</div>`).join('')}</details></article>`).join('');
    if(more)list.insertAdjacentHTML('beforeend',html);else list.innerHTML=html||'<div class="g-card g-muted">Действий по этим фильтрам пока нет.</div>';
    toolsState.logCursor=data.next_cursor;document.getElementById('tools-logs-more').hidden=!data.next_cursor;
  } catch(error) { if(requestId===toolsLogRequest)list.innerHTML=`<div class="g-card g-muted">${toolsEsc(error.message)}</div>`; }
}
async function toolsStorage() {
  await toolsRun('storage',async()=>{
    const data=await toolsRequest('/api/admin/storage');
    const ephemeral=data.render&&(!data.persistent_database||!data.persistent_uploads);
    document.getElementById('tools-storage-status').innerHTML=`<p>База: ${data.persistent_database?'внешняя или на постоянном диске':'локальная SQLite'}.</p><p>Фотографии: ${data.persistent_uploads?'на постоянном диске':'в локальной папке сервера'}.</p><p>Копий на сервере: ${data.backup_count}. Последняя: ${toolsEsc(data.last_backup||'ещё не создана')}.</p>${ephemeral?'<div class="g-note">На этом Render-хостинге локальные данные могут исчезнуть после перезапуска. Скачивайте копии. Для постоянного хранения настройте внешнюю PostgreSQL и постоянный диск для файлов.</div>':''}`;
  });
}
async function toolsBackup() {
  await toolsRun('backup',async()=>{
    const response=await fetch('/api/admin/backup',{headers:API._getHeaders()});
    if(!response.ok)throw new Error('Не удалось создать резервную копию');
    toolsSaveBlob(await response.blob(),`gym16-backup-${new Date().toISOString().slice(0,10)}.zip`);toolsToast('Архив подготовлен');
  });
}

// Explicitly export replacements used by inline handlers and existing listeners.
Object.assign(window,{loadSchedule,renderLessonSlot,switchTab,setAdminSubtab,handleModeratePost,togglePostReaction,loadEgeMaterials,renderSingleEgeMaterialCard,renderNewsPost});
// Repaint any schedule that was fetched before this script was loaded.
loadSchedule();

const toolsOriginalEgeSave = handleSaveEgeMaterial;
document.getElementById('save-ege-modal-btn').dataset.busy = 'ege-save';
handleSaveEgeMaterial = function(event) { event.preventDefault(); return toolsRun('ege-save', () => toolsOriginalEgeSave(event)); };
window.handleSaveEgeMaterial = handleSaveEgeMaterial;
setInterval(() => {
  if (!document.hidden && !document.getElementById('tab-schedule').classList.contains('hidden')) loadSchedule(true);
}, 60000);
