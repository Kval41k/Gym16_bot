/* Authenticated learning tools: the browser never receives answer keys before submission. */
const school={practice:null,practiceTicket:0,progress:{},group:null,catalogLoaded:false};
function schoolReminderPreview(){const slider=document.getElementById('tools-reminder-minutes');if(!slider)return;const n=Number(slider.value);slider.style.setProperty('--reminder-fill',`${(n-5)*10}%`);slider.setAttribute('aria-valuetext',`За ${n} минут`);document.getElementById('school-reminder-value').textContent=`За ${n} минут`;document.querySelectorAll('[data-reminder-minutes]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.reminderMinutes)===n)));}
function schoolChooseReminder(n){document.getElementById('tools-reminder-minutes').value=n;schoolReminderPreview();}
schoolReminderPreview();

// Explicit groups show both halves by default; personal group is saved separately in the profile.
document.getElementById('schedule-profile-filter-container').insertAdjacentHTML('afterend',`<p class="g-muted" id="school-track-hint" hidden>11В: выбери «Инфотех» или «Инженеры». Общие уроки отображаются в обоих профилях.</p><div class="g-tabs school-groups" role="group" aria-label="Подгруппа в расписании"><button class="g-btn primary" data-school-group="" onclick="schoolChooseGroup(null)">Обе группы</button><button class="g-btn" data-school-group="1" onclick="schoolChooseGroup(1)">1 группа</button><button class="g-btn" data-school-group="2" onclick="schoolChooseGroup(2)">2 группа</button></div>`);
function schoolViewingGroup(){return school.group;}
function schoolChooseGroup(value){school.group=value;document.querySelectorAll('[data-school-group]').forEach(button=>button.classList.toggle('primary',button.dataset.schoolGroup===(value?String(value):'')));loadSchedule();}
window.schoolViewingGroup=schoolViewingGroup;
const schoolProfileFilters=renderScheduleProfileFilters;
renderScheduleProfileFilters=function(){schoolProfileFilters();document.getElementById('school-track-hint').hidden=(state.viewingClass||state.user.class_name)!=='11В';const groups=document.querySelector('.school-groups');if(groups){groups.hidden=!['11Б','11Г','11Д','11Ж'].includes(state.viewingClass||state.user.class_name);if(groups.hidden)school.group=null;}};
renderScheduleProfileFilters();
const groupAnchor=document.getElementById('onboarding-profiles-list');
groupAnchor.insertAdjacentHTML('afterend',`<label class="g-label" for="school-profile-group">Подгруппа английского / информатики</label><select id="school-profile-group" class="g-input"><option value="">Не выбрана — показывать обе</option><option value="1">1 группа</option><option value="2">2 группа</option></select><p class="g-muted">Используется в личной карточке и напоминаниях, если в классе есть занятия по группам.</p>`);
const schoolOnboard=openOnboardingModal;
openOnboardingModal=function(){document.getElementById('school-profile-group').value=state.user.subgroup||'';return schoolOnboard();};
document.getElementById('edit-profile-btn').removeEventListener('click',schoolOnboard);
document.getElementById('edit-profile-btn').addEventListener('click',()=>openOnboardingModal());

// The format notice distinguishes the FIPI draft from the original training notes and exercises.
document.getElementById('ege-materials-list').insertAdjacentHTML('beforebegin',`<section class="g-card school-ege-overview"><div class="g-badge">ЕГЭ-2027 · проект ФИПИ</div><h3 class="g-title">Теория → практика → повторение ошибок</h3><p class="g-muted">27 тем русского языка и 20 тем профильной математики. Учебные конспекты и мини-задания; формат сверен 25.10.2026.</p><p class="g-muted" id="school-practice-summary"></p><p class="g-muted">Для сочинения и развёрнутых задач проверяются отдельные навыки, а не полный экзаменационный ответ.</p><a class="g-btn" href="https://fipi.ru/ege/demoversii-specifikacii-kodifikatory" target="_blank" rel="noopener noreferrer">Документы ФИПИ-2027 ↗</a></section>`);
async function schoolLoadProgress(){if(state.user.access_allowed===false)return;const ticket=(school.progressTicket||0)+1;school.progressTicket=ticket;try{const result=await toolsRequest('/api/me/practice/progress');if(ticket!==school.progressTicket)return;school.progress=result;schoolProgressSummary();}catch(_){}}
function schoolProgressSummary(){const sub=state.ege.activeSubject||'russian';const values=Object.entries(school.progress).filter(([key])=>key.startsWith(sub+':')).map(([,value])=>value);document.getElementById('school-practice-summary').textContent=`Тренажёр: решено ${values.reduce((a,v)=>a+v.mastered,0)} из ${values.reduce((a,v)=>a+v.total,0)} · ошибок для повторения: ${values.reduce((a,v)=>a+v.mistakes,0)}`;}
const schoolEgeCard=renderSingleEgeMaterialCard;
renderSingleEgeMaterialCard=function(material,isAdmin){return schoolEgeCard(material,isAdmin).replace('</article>',`<button class="g-btn primary school-practice-button" onclick="schoolPractice('${material.subject_code}',${Number(material.task_number)})">Тренажёр задания №${Number(material.task_number)} →</button></article>`);};
const schoolRenderToolsEge=toolsRenderEge;
toolsRenderEge=function(){schoolRenderToolsEge();schoolProgressSummary();};
const schoolPersonal=loadPersonalTools;
loadPersonalTools=async function(){await Promise.allSettled([schoolPersonal(),schoolLoadProgress()]);};
window.loadPersonalTools=loadPersonalTools;

// Dialog with a single submit path; session tokens make duplicate requests idempotent server-side.
document.body.insertAdjacentHTML('beforeend',`<dialog id="school-practice-dialog" class="g-editor school-practice-dialog" aria-labelledby="school-practice-title"><div class="g-row g-between"><h3 id="school-practice-title" class="g-title">Тренажёр</h3><button type="button" class="g-btn" aria-label="Закрыть тренажёр" onclick="schoolClosePractice()">✕</button></div><p class="g-muted" id="school-practice-scope"></p><div class="g-row school-practice-modes"><button class="g-btn primary" id="school-practice-all" onclick="schoolPracticeMode('all')">Новые и повторение</button><button class="g-btn" id="school-practice-errors" onclick="schoolPracticeMode('mistakes')">Только ошибки</button></div><div id="school-practice-body" class="g-stack"></div><p id="school-practice-error" class="g-error" role="alert"></p></dialog>`);
function schoolClosePractice(){school.practiceTicket++;document.getElementById('school-practice-dialog').close();}
async function schoolPractice(subject,number){school.practice={subject,number,mode:'all'};const dialog=document.getElementById('school-practice-dialog');if(!dialog.open)dialog.showModal();await schoolNextPractice();}
function schoolPracticeMode(mode){if(!school.practice)return;school.practice.mode=mode;schoolNextPractice();}
async function schoolNextPractice(){
  if(!school.practice)return;
  const ticket=++school.practiceTicket;const {subject,number,mode}=school.practice;
  if(school.answerSaving)try{await school.answerSaving;}catch(_){}
  if(ticket!==school.practiceTicket)return;
  document.getElementById('school-practice-title').textContent=`Задание №${number} · ${subject==='math'?'Профильная математика':'Русский язык'}`;
  document.getElementById('school-practice-all').classList.toggle('primary',mode==='all');document.getElementById('school-practice-errors').classList.toggle('primary',mode==='mistakes');
  document.getElementById('school-practice-error').textContent='';document.getElementById('school-practice-body').innerHTML='<p class="g-muted">Подбираем задачу…</p>';
  try{
    const data=await toolsRequest('/api/me/practice/next?'+new URLSearchParams({subject_code:subject,task_number:number,mode}));
    if(ticket!==school.practiceTicket)return;
    school.practice.data=data;
    const stats=data.stats;document.getElementById('school-practice-scope').textContent=`Решено ${stats.mastered}/${stats.total} · ошибок для повторения ${stats.mistakes}${data.scope?' · '+data.scope:''}`;
    if(!data.question){document.getElementById('school-practice-body').innerHTML=`<p class="g-note">${toolsEsc(data.message)}</p>${stats.mistakes&&mode==='all'?'<button class="g-btn primary" onclick="schoolPracticeMode(\'mistakes\')">Повторить ошибки сейчас</button>':''}`;return;}
    const q=data.question;
    const answers=q.kind==='choice'?`<fieldset class="school-answer-options"><legend class="g-label">Выбери ответ</legend>${q.options.map(option=>`<label><input type="radio" name="school-answer" value="${toolsEsc(option.id)}" required><span>${toolsEsc(option.text)}</span></label>`).join('')}</fieldset>`:`<label class="g-label" for="school-answer">${q.kind==='number'?'Числовой ответ':'Ответ словом или буквой'}</label><input id="school-answer" class="g-input" name="school-answer" maxlength="1000" required autocomplete="off" ${q.kind==='number'?'inputmode="decimal" placeholder="Например: 0,25 или 1/4"':'autocapitalize="off" spellcheck="false"'}>`;
    document.getElementById('school-practice-body').innerHTML=`<p class="g-muted">${toolsEsc(data.notice)}</p><p class="school-question">${toolsEsc(q.prompt)}</p><form onsubmit="schoolSubmitPractice(event)" class="g-stack">${answers}<button class="g-btn primary school-practice-submit" type="submit">Проверить ответ</button></form><div id="school-practice-feedback" aria-live="polite"></div>`;
  }catch(error){if(ticket===school.practiceTicket)document.getElementById('school-practice-error').textContent=error.message;}
}
async function schoolSubmitPractice(event){
  event.preventDefault();
  const form=event.currentTarget,button=form.querySelector('button[type="submit"]');if(button.disabled)return;
  const q=school.practice.data.question;const answer=q.kind==='choice'?form.querySelector('input[name="school-answer"]:checked')?.value:form.querySelector('#school-answer').value.trim();if(!answer)return;
  const session=school.practice.data.session_id,ticket=school.practiceTicket;button.disabled=true;
  try{
    school.answerSaving=toolsRequest('/api/me/practice/answer','POST',{session_id:session,answer});
    const result=await school.answerSaving;if(ticket!==school.practiceTicket)return;
    form.querySelectorAll('input').forEach(input=>input.disabled=true);button.textContent='Ответ сохранён';
    document.getElementById('school-practice-feedback').innerHTML=`<div class="school-feedback ${result.correct?'correct':'incorrect'}"><h4 class="g-title">${result.correct?'Верно ✓':'Пока ошибка — разберём решение'}</h4><p><b>Ответ:</b> ${toolsEsc(result.correct_answer)}</p><p>${toolsEsc(result.explanation)}</p><p class="g-muted">${result.correct?'Эта задача решена и больше не появится.':'Ошибка сохранена. Вернёмся к этой задаче при повторении.'}</p>${result.notice?`<p class="g-muted">${toolsEsc(result.notice)}</p>`:''}</div><button class="g-btn primary school-practice-button" onclick="schoolNextPractice()">Следующая задача →</button>`;
    await schoolLoadProgress();
    if(ticket===school.practiceTicket){const stats=school.progress[`${school.practice.subject}:${school.practice.number}`];if(stats)document.getElementById('school-practice-scope').textContent=`Решено ${stats.mastered}/${stats.total} · ошибок для повторения ${stats.mistakes} · ${school.practice.data.scope}`;}
  }catch(error){if(ticket===school.practiceTicket){button.disabled=false;document.getElementById('school-practice-error').textContent=error.message;}}
  finally{school.answerSaving=null;}
}
Object.assign(window,{renderSingleEgeMaterialCard,toolsRenderEge,openOnboardingModal,schoolReminderPreview});
