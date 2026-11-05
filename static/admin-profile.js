/* Profile administration is authorized independently on every server request. */
document.body.insertAdjacentHTML('beforeend', `<dialog id="admin-person-dialog" class="g-editor"><form id="admin-person-form" class="g-stack"><h3 class="g-title">Изменить имя пользователя</h3><p class="g-muted">Имя в приложении. Telegram @username не меняется.</p><label class="g-label">Имя<input class="g-input" name="first_name" required minlength="2" maxlength="100"></label><label class="g-label">Фамилия<input class="g-input" name="last_name" required minlength="2" maxlength="100"></label><p class="g-error" role="alert"></p><div class="g-row"><button class="g-btn" type="button" data-admin-person-close>Отмена</button><button class="g-btn primary" type="submit">Сохранить</button></div></form></dialog>`);
document.addEventListener('click', async event => {
  if (event.target.closest('[data-admin-person-close]')) { document.getElementById('admin-person-dialog').close(); return; }
  const button = event.target.closest('[data-admin-person]');
  if (!button || !checkIsAdmin()) return;
  const id = Number(button.dataset.userId), user = cachedAdminUsers.find(row => row.id === id);
  if (!user) return;
  if (button.dataset.adminPerson === 'name') {
    const form = document.getElementById('admin-person-form'); form.dataset.userId = id;
    form.elements.first_name.value = user.first_name || ''; form.elements.last_name.value = user.last_name || '';
    form.querySelector('.g-error').textContent = ''; document.getElementById('admin-person-dialog').showModal(); return;
  }
  if (!await communityConfirm(`Удалить регистрацию ${user.first_name} ${user.last_name || ''}?\nПользователь исчезнет из списка и должен будет заново указать имя, фамилию, класс и профиль. Роли редактора и старосты будут сняты. История публикаций и действий сохраняется.`)) return;
  button.disabled = true;
  try { await toolsRequest(`/api/admin/users/${id}/reset-registration`, 'POST', {}); await loadAdminUsers(); toolsToast('Регистрация удалена'); }
  catch(error) { toolsToast(error.message); } finally { button.disabled = false; }
});
document.getElementById('admin-person-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type=submit]');
  if (button.disabled) return; button.disabled = true;
  try {
    await toolsRequest(`/api/admin/users/${form.dataset.userId}/name`, 'PUT', {first_name:form.elements.first_name.value.trim(), last_name:form.elements.last_name.value.trim()});
    if (Number(form.dataset.userId) === state.user.id) {
      state.user.first_name = form.elements.first_name.value.trim(); state.user.last_name = form.elements.last_name.value.trim();
      saveProfileLocally(state.user); updateProfileUI();
    }
    document.getElementById('admin-person-dialog').close(); await loadAdminUsers(); toolsToast('Имя обновлено');
  } catch(error) { form.querySelector('.g-error').textContent = error.message; } finally { button.disabled = false; }
});
