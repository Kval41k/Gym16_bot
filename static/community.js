/* Daily school tools extend the existing navigation and verified API. */
document.body.insertAdjacentHTML('beforeend', `<dialog id="community-confirm" class="g-editor" aria-label="Подтверждение изменения"><form method="dialog"><h3 class="g-title">Проверьте изменение</h3><p id="community-confirm-text" style="white-space:pre-wrap;max-height:45vh;overflow:auto;margin:16px 0"></p><div class="g-row"><button class="g-btn" value="cancel">Отмена</button><button class="g-btn primary" value="accept">Подтвердить</button></div></form></dialog>`);
function communityConfirm(message) {
  const dialog=document.getElementById('community-confirm');
  document.getElementById('community-confirm-text').textContent=message;
  dialog.returnValue='cancel';dialog.showModal();
  return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='accept'),{once:true}));
}
const community = {newsTicket:0,offset:0,query:'',more:false,dateEditor:null,draft:null,draftQueue:null,draftSaving:null,draftReady:false,draftSkip:false};
const communityISO = value => `${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
function communityToday() { return communityISO(getTyumenDate()); }
function communityParseDate(value) { const [y,m,d]=value.split('-').map(Number);return new Date(y,m-1,d,12); }
function communityMonday(value) { const result=new Date(value);result.setDate(result.getDate()-((result.getDay()+6)%7));return result; }
community.week=communityMonday(getTyumenDate());
if (getTyumenDate().getDay()===0) community.week.setDate(community.week.getDate()+7);
function communityScheduleDate(day) {const value=new Date(community.week);value.setDate(value.getDate()+day);return communityISO(value);}
function communityDateLabel() {
  const node=document.getElementById('tools-schedule-date');
  if(node)node.textContent=(toolsState.mode==='week'?'Учебная неделя':communityParseDate(communityScheduleDate(state.selectedDay)).toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'}))+' · '+(state.viewingClass||state.user.class_name||'11А');
}
// Students browse weekdays and today; arbitrary date selection belongs to administration.
toolsToday=function(){community.week=communityMonday(getTyumenDate());const day=getTyumenDate().getDay();state.selectedDay=day===0?6:day-1;toolsState.mode='day';if(state.selectedDay<6)selectDay(state.selectedDay);else loadSchedule();};

// One personal live card; browsing another class never changes this account's status.
function communityLiveScope(){return JSON.stringify([state.user?.id,state.user?.class_name,state.user?.profile_name,state.user?.subgroup,state.user?.access_allowed]);}
function communityLiveParams(){const params=new URLSearchParams();if(state.user?.class_name)params.set('class_name',state.user.class_name);if(state.user?.profile_name)params.set('profile_name',state.user.profile_name);if(state.user?.subgroup)params.set('subgroup',state.user.subgroup);return params;}
function communityLessonStamp(item,field){return item?.date&&/^\d\d:\d\d$/.test(item[field]||'')?Date.parse(item.date+'T'+item[field]+':00+05:00'):NaN;}
function communityLessonDescription(item){return [...new Set((item?.lessons||[]).map(row=>row.subject+(row.cabinet?' · каб. '+row.cabinet:'')))].join(' / ');}
function communityCountdown(target,now){const seconds=Math.max(0,Math.ceil((target-now)/1000));return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');}
function communityLiveModel(personal,live,receivedAt,clientNow=Date.now()){
  const serverTime=Date.parse(personal?.now||'');
  const now=Number.isFinite(serverTime)?serverTime+Math.max(0,clientNow-receivedAt):clientNow;
  const wall=new Date(now+5*3600000),today=wall.toISOString().slice(0,10),clock=wall.toISOString().slice(11,16);
  const model={clock,today,title:'Моё расписание',message:live?.message||'Уточняем время занятий…',countdown:'',next:null};
  if(live?.state==='no_schedule'){model.title='Расписание ещё не загружено';return model;}
  const items=[personal?.current,personal?.next].filter(Boolean);
  const current=items.find(item=>communityLessonStamp(item,'start_time')<=now&&now<communityLessonStamp(item,'end_time'));
  const next=items.find(item=>communityLessonStamp(item,'start_time')>now);
  if(next)model.next={description:communityLessonDescription(next),date:next.date,start:next.start_time,end:next.end_time};
  if(current){
    model.title='Сейчас идёт урок';model.message=communityLessonDescription(current);
    model.countdown='До конца урока · '+communityCountdown(communityLessonStamp(current,'end_time'),now);
    return model;
  }
  if(next?.date===today){
    const hadCurrent=personal?.current?.date===today&&communityLessonStamp(personal.current,'end_time')<=now;
    const onBreak=live?.state==='break'||hadCurrent;
    model.title=onBreak?'Перемена':'До начала занятий';
    model.message=onBreak?'Можно отдохнуть перед следующим уроком':'Первое занятие ещё не началось';
    model.countdown=(onBreak?'До конца перемены · ':'До первого занятия · ')+communityCountdown(communityLessonStamp(next,'start_time'),now);
    return model;
  }
  if(personal){
    const weekend=wall.getUTCDay()===0||live?.state==='weekend';
    model.title=weekend?'Сегодня выходной':live?.state==='after_school'&&/нет занятий/.test(live.message||'')?'Сегодня занятий нет':'Занятия на сегодня закончились';
    model.message=weekend?'Уроков сегодня нет':live?.state==='after_school'?live.message:'Можно отдохнуть';
    if(!next)model.message=live?.state==='no_schedule'?live.message:'На ближайшую неделю занятий нет';
    return model;
  }
  // Signed membership can be unavailable; keep the public personal-class status visible.
  model.title=live?.state==='lesson'?'Сейчас идёт урок':live?.state==='break'?'Перемена':live?.state==='before_school'?'До начала занятий':live?.state==='weekend'?'Сегодня выходной':'Статус занятий';
  if(live?.next_lesson_time)model.countdown='Следующее занятие в '+live.next_lesson_time;
  return model;
}
function communityRenderLive(){
  const node=document.getElementById('live-status-card');if(!node)return;
  node.classList.add('community-live-card');
  const cache=community.liveCache,valid=cache&&cache.scope===communityLiveScope()&&Date.now()-cache.receivedAt<90000;
  const model=valid?communityLiveModel(cache.personal,cache.live,cache.receivedAt):{clock:getTyumenTime(),title:'Моё расписание',message:state.user?.class_name?'Уточняем время занятий…':'Выбери класс и профиль в настройках',countdown:'',next:null};
  const cls=state.user?.class_name||'';
  const next=model.next;
  const nextLabel=next?(next.date===(model.today||communityToday())?'Дальше':communityParseDate(next.date).toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'})):'';
  const html=`<div class="community-live-head"><div id="live-status-title" class="g-muted">${toolsEsc(model.title)}${cls?' · '+toolsEsc(cls):''}</div><time id="live-status-time" class="g-badge">${toolsEsc(model.clock)}</time></div><h3 id="live-status-message" class="g-title">${toolsEsc(model.message)}</h3>${model.countdown?`<p class="community-live-countdown">${toolsEsc(model.countdown)}</p>`:''}${next?`<div class="community-live-next"><span class="g-muted">${toolsEsc(nextLabel)} · ${toolsEsc(next.start)}–${toolsEsc(next.end)}</span><p>${toolsEsc(next.description)}</p></div>`:''}`;
  if(node.innerHTML!==html)node.innerHTML=html;
}
calculateLiveStatusLocally=communityRenderLive;
updateLiveScheduleStatus=async function(){
  const scope=communityLiveScope();
  if(community.liveRequest?.scope===scope)return community.liveRequest.promise;
  const ticket=(community.liveTicket||0)+1;community.liveTicket=ticket;
  if(!state.user?.class_name){community.liveCache=null;communityRenderLive();return;}
  const fetch=async()=>{
    const results=await Promise.allSettled([API.get('/api/schedule/live?'+communityLiveParams()),state.user.access_allowed===false?Promise.resolve(null):toolsRequest('/api/me/next-lesson')]);
    if(ticket!==community.liveTicket||scope!==communityLiveScope())return;
    const live=results[0].status==='fulfilled'?results[0].value:null,personal=results[1].status==='fulfilled'?results[1].value:null;
    if(live||personal)community.liveCache={scope,live,personal,receivedAt:Date.now()};
    communityRenderLive();
  };
  const promise=fetch();community.liveRequest={scope,promise};
  try{await promise;}finally{if(community.liveRequest?.promise===promise)community.liveRequest=null;}
};
Object.assign(window,{updateLiveScheduleStatus,calculateLiveStatusLocally});
communityRenderLive();
setInterval(()=>{if(!document.hidden)communityRenderLive();},1000);

// Search is performed before pagination on the server; pinned announcements come first.
document.getElementById('news-posts-list').insertAdjacentHTML('beforebegin',`<label class="g-label" for="community-news-search">Поиск по школьной ленте</label><input id="community-news-search" class="g-input" type="search" maxlength="120" placeholder="Заголовок или текст новости" data-gym-input="hf4eeba908e3c">`);
document.getElementById('news-posts-list').insertAdjacentHTML('afterend',`<button id="community-news-more" class="g-btn" hidden data-gym-click="h3d7248722c82">Показать ещё новости</button>`);
let communitySearchTimer;
function communitySearchNews(){clearTimeout(communitySearchTimer);community.newsTicket++;communitySearchTimer=setTimeout(()=>loadNews(),300);}
loadNews=async function(more=false){
  const ticket=++community.newsTicket;
  const query=document.getElementById('community-news-search').value.trim();
  if(!more){community.offset=0;community.query=query;}
  const offset=more?community.offset:0;
  const container=document.getElementById('news-posts-list');
  const button=document.getElementById('community-news-more');button.disabled=true;
  try{
    const posts=await toolsRequest('/api/news?'+new URLSearchParams({q:query,limit:20,offset}));
    if(ticket!==community.newsTicket)return;
    state.news=more?[...state.news,...posts.filter(p=>!state.news.some(old=>old.id===p.id))]:posts;
    community.offset=offset+posts.length;community.more=posts.length===20;
    container.innerHTML=state.news.map(p=>renderNewsPost(p)).join('')||`<div class="g-card g-muted">${query?'По этому запросу новостей нет.':'В ленте пока нет новостей.'}</div>`;
    button.hidden=!community.more||toolsState.news!=='feed';
  }catch(error){if(ticket===community.newsTicket)container.innerHTML=`<div class="g-card g-muted">${toolsEsc(error.message)} <button class="g-btn" data-gym-click="h84dc45fa52e5">Повторить</button></div>`;}
  finally{if(ticket===community.newsTicket)button.disabled=false;}
};
function communityMoreNews(){if(!document.getElementById('community-news-more').disabled)loadNews(true);}
const communityRenderNews=renderNewsPost;
renderNewsPost=function(post){return communityRenderNews(post).replace('<!-- Post Content -->',`${post.is_pinned?'<div class="g-badge">📌 Закреплённое объявление</div>':''}${checkCanEdit()?`<button class="g-btn" data-busy="pin-${post.id}" data-gym-click="hca2c83ec0af6" data-gym-args="${encodeURIComponent(JSON.stringify([(post.id),(!post.is_pinned)]))}">${post.is_pinned?'Снять закрепление':'Закрепить'}</button>`:''}<!-- Post Content -->`);};
async function communityPin(id,pinned){await toolsRun('pin-'+id,async()=>{await toolsRequest(`/api/news/${id}/pin`,'PUT',{pinned});await loadNews();toolsToast(pinned?'Объявление закреплено':'Закрепление снято');});}
const communityNewsTab=toolsNewsTab;
toolsNewsTab=async function(tab){await communityNewsTab(tab);document.getElementById('community-news-search').hidden=tab!=='feed';document.querySelector('label[for="community-news-search"]').hidden=tab!=='feed';document.getElementById('community-news-more').hidden=tab!=='feed'||!community.more;};

// One revisioned draft per account, saved on the server. Files remain explicit uploads.
document.getElementById('propose-content').insertAdjacentHTML('afterend',`<p class="g-muted" id="community-draft-status" role="status">Текст черновика сохраняется автоматически. Фото нужно выбрать заново после закрытия.</p><button type="button" class="g-btn" data-gym-click="h150f9ed7ba5b">Перечитать сохранённый черновик</button>`);
async function communityReloadDraft(){if(!await communityConfirm('Загрузить сохранённый черновик заново? Текст в редакторе будет заменён. Если его нужно сохранить, сначала скопируйте его.'))return;clearTimeout(communityDraftTimer);if(community.draftSaving)try{await community.draftSaving;}catch(_){}community.draftQueue=null;await window.communityDraftOpen();}
function communityDraftSnapshot(){return {title:document.getElementById('propose-title').value,content:document.getElementById('propose-content').value,is_anonymous:document.getElementById('propose-anonymous').checked};}
function communityDraftStatus(text){document.getElementById('community-draft-status').textContent=text;}
let communityDraftTimer;
window.communityDraftOpen=async function(){
  const ticket=(community.draftOpenTicket||0)+1;community.draftOpenTicket=ticket;
  community.draftReady=false;
  const fields=['propose-title','propose-content','propose-anonymous'].map(id=>document.getElementById(id));fields.forEach(el=>el.disabled=true);
  document.getElementById('submit-news-btn').disabled=true;
  try{
    if(community.draftSaving)await community.draftSaving;
    const draft=await toolsRequest('/api/me/news-draft');if(ticket!==community.draftOpenTicket)return;community.draft=draft;
    fields[0].value=draft.title;fields[1].value=draft.content;fields[2].checked=draft.is_anonymous;
    community.draftReady=true;communityDraftStatus('Черновик загружен. Текст сохраняется автоматически; фото после закрытия нужно выбрать заново.');
  }catch(error){if(ticket===community.draftOpenTicket)communityDraftStatus(error.message+' Попробуйте перечитать черновик.');}
  finally{if(ticket===community.draftOpenTicket){fields.forEach(el=>el.disabled=!community.draftReady);document.getElementById('submit-news-btn').disabled=!community.draftReady;}}
};
function communityQueueDraft(){if(!community.draftReady)return;community.draftQueue=communityDraftSnapshot();communityDraftStatus('Есть несохранённые изменения…');clearTimeout(communityDraftTimer);communityDraftTimer=setTimeout(()=>communitySaveDraft().catch(()=>{}),700);}
['propose-title','propose-content','propose-anonymous'].forEach(id=>document.getElementById(id).addEventListener('input',communityQueueDraft));
async function communitySaveDraft(){
  if(community.draftSaving)return community.draftSaving;
  const task=(async()=>{
    while(community.draftQueue){
      const snapshot=community.draftQueue;community.draftQueue=null;
      try{const saved=await toolsRequest('/api/me/news-draft','PUT',{...snapshot,revision:community.draft?.revision||''});community.draft={...snapshot,...saved};communityDraftStatus('Черновик сохранён. Фото после закрытия нужно выбрать заново.');}
      catch(error){community.draftQueue=snapshot;communityDraftStatus(error.message+' Текст остался в редакторе.');throw error;}
    }
  })();
  community.draftSaving=task;
  try{await task;}finally{community.draftSaving=null;}
}
window.communityDraftFlush=async function(){clearTimeout(communityDraftTimer);if(community.draftReady)community.draftQueue=communityDraftSnapshot();await communitySaveDraft();};
window.communityDraftClose=async function(){
  if(community.draftSkip){community.draftSkip=false;return true;}
  if(!community.draftReady)return true;
  try{await window.communityDraftFlush();return true;}catch(error){toolsToast('Черновик не сохранён. Скопируйте текст или повторите закрытие после восстановления сети.');return false;}
};
window.communityDraftSent=async function(){
  clearTimeout(communityDraftTimer);if(community.draftSaving)await community.draftSaving;
  community.draftQueue=null;
  try{const saved=await toolsRequest('/api/me/news-draft','PUT',{title:'',content:'',is_anonymous:false,revision:community.draft?.revision||''});community.draft={title:'',content:'',is_anonymous:false,...saved};}
  catch(_){toolsToast('Новость отправлена. Черновик не удалось очистить; перед повторной отправкой проверьте «Мои предложения».');}
  community.draftSkip=true;
};

// Membership gate is separate from profile completion and cannot grant editorial rights.
document.body.insertAdjacentHTML('beforeend',`<dialog id="community-access-gate" class="g-editor" aria-labelledby="community-access-title"><form data-gym-submit="hbc95084ef88f"><h3 id="community-access-title" class="g-title">Добро пожаловать в Г16</h3><p class="g-muted">Для доступа к школьной ленте и материалам введи код приглашения от администратора.</p><label class="g-label" for="community-invite-code">Код приглашения</label><input id="community-invite-code" class="g-input" required minlength="10" maxlength="80" autocomplete="off" spellcheck="false"><p id="community-invite-error" class="g-error" role="alert"></p><button class="g-btn primary" data-busy="redeem">Войти в школьное сообщество</button><button type="button" class="g-btn" data-gym-click="h4cc20ce0c043">Пока только расписание</button></form></dialog>`);
window.communityAccessGate=function(user){
  if(user.access_allowed!==false)return false;
  const node=document.getElementById('community-access-gate');if(!node.open)node.showModal();return true;
};
document.getElementById('edit-profile-btn').insertAdjacentHTML('afterend',`<button class="g-btn" data-gym-click="hdbb481683a63">Ввести код приглашения</button>`);
async function communityRedeem(){await toolsRun('redeem',async()=>{try{await toolsRequest('/api/access/redeem','POST',{code:document.getElementById('community-invite-code').value.trim()});location.reload();}catch(error){document.getElementById('community-invite-error').textContent=error.message;}});}
window.communityRoleUI=function(){
  if (state.user?.role==='editor' && !checkIsAdmin()) { const heading=document.querySelector('#tab-admin h2');if(heading){heading.textContent='✎ Редактор';if(heading.nextElementSibling)heading.nextElementSibling.textContent='Модерация новостей и работа с материалами ЕГЭ';}if(!document.getElementById('tab-admin').classList.contains('hidden'))document.getElementById('app-title').textContent='Редактор'; }
  const label=document.querySelector('#nav-tab-admin > span');if(label)label.textContent=checkIsAdmin()?'Админ':'Редактор';
  ['users','schedule','logs','data','access'].forEach(id=>{const button=document.getElementById('admin-subtab-'+id+'-btn');if(button)button.hidden=!checkIsAdmin();});
};
const communitySwitchTab=switchTab;
switchTab=function(tab){if(state.user.access_allowed===false && tab!=='tab-schedule'&&tab!=='tab-profile'){window.communityAccessGate(state.user);return;}communitySwitchTab(tab);communityRoleUI();};
async function communitySetRole(id,role){if(!await communityConfirm(role==='editor'?'Редактор сможет редактировать и модерировать новости и материалы ЕГЭ. Назначить?':'Снять полномочия редактора?'))return;await toolsRun('role-'+id,async()=>{await toolsRequest(`/api/admin/users/${id}/role`,'PUT',{role});await loadAdminUsers();toolsToast('Роль обновлена');});}

document.getElementById('tab-admin').insertAdjacentHTML('beforeend',`<section id="admin-section-access" hidden class="g-stack"><div class="g-card g-stack"><h3 class="g-title">Доступ по приглашениям</h3><p class="g-muted">Действующие участники сохраняют доступ. Когда режим включён, новым аккаунтам нужен код. Роль редактора назначается отдельно в «Пользователи».</p><label class="g-row"><input type="checkbox" id="community-access-required"> Требовать приглашение для новых пользователей</label><button class="g-btn primary" data-busy="access-policy" data-gym-click="h359caf04b65f">Сохранить режим доступа</button></div><form class="g-card g-stack" data-gym-submit="hfafefbafbf51"><h3 class="g-title">Создать приглашение</h3><label class="g-label">Название<input class="g-input" id="community-invite-label" maxlength="80" required placeholder="Например, 11А"></label><label class="g-label">Количество активаций<input class="g-input" type="number" id="community-invite-uses" value="1" min="1" max="1000" required></label><label class="g-label">Действует дней<input class="g-input" type="number" id="community-invite-days" value="7" min="1" max="90" required></label><button class="g-btn primary" data-busy="invite-create">Создать код</button><div id="community-new-code" hidden></div></form><div id="community-invites-list"></div></section>`);
async function communityLoadAccess(){try{const data=await toolsRequest('/api/admin/access');document.getElementById('community-access-required').checked=data.invites_required;document.getElementById('community-invites-list').innerHTML=data.invites.map(row=>`<article class="g-card"><h4 class="g-title">${toolsEsc(row.label)}</h4><p class="g-muted">${row.uses} / ${row.max_uses} активаций · до ${toolsDate(row.expires_at)}${row.revoked?' · отозван':''}</p>${!row.revoked?`<button class="g-btn danger" data-busy="revoke-${row.id}" data-gym-click="h0409ad5fffe0" data-gym-args="${encodeURIComponent(JSON.stringify([(row.id)]))}">Отозвать код</button>`:''}</article>`).join('')||'<p class="g-muted">Приглашений пока нет.</p>';}catch(error){toolsToast(error.message);}}
async function communitySaveAccess(){await toolsRun('access-policy',async()=>{await toolsRequest('/api/admin/access','PUT',{invites_required:document.getElementById('community-access-required').checked});toolsToast('Режим доступа сохранён');});}
async function communityCreateInvite(){await toolsRun('invite-create',async()=>{const data=await toolsRequest('/api/admin/invites','POST',{label:document.getElementById('community-invite-label').value.trim(),max_uses:Number(document.getElementById('community-invite-uses').value),days:Number(document.getElementById('community-invite-days').value)});const node=document.getElementById('community-new-code');node.hidden=false;node.innerHTML=`<label class="g-label">Код — показывается один раз<input class="g-input g-selectable" readonly value="${toolsEsc(data.code)}"></label><p class="g-muted">Скопируй код и передай ученикам. Срок: ${toolsDate(data.expires_at)}.</p>`;await communityLoadAccess();});}
async function communityRevokeInvite(id){await toolsRun('revoke-'+id,async()=>{await toolsRequest(`/api/admin/invites/${id}/revoke`,'POST',{});await communityLoadAccess();});}

// Dated changes have their own form, confirmation and revision, distinct from weekly publishing.
document.getElementById('admin-section-schedule').insertAdjacentHTML('afterbegin',`<section class="g-card g-stack"><h3 class="g-title">Замены и отмены на дату</h3><p class="g-muted">Изменения действуют только в выбранный день. Обычная учебная неделя сохраняется. Перед публикацией проверьте оба профиля класса.</p><label class="g-label">Класс<select class="g-input" id="community-date-class"></select></label><label class="g-label">Дата<input class="g-input" type="date" id="community-date-edit" value="${communityToday()}"></label><button class="g-btn" data-busy="date-load" data-gym-click="h2b59af75a3f9">Загрузить день</button><div id="community-date-body" hidden><p class="g-muted" id="community-date-caption"></p><label class="g-label">Объявление для класса<input class="g-input" id="community-date-note" maxlength="255" placeholder="Например, замена кабинета"></label><div id="community-date-rows"></div><div class="g-row"><button class="g-btn" data-gym-click="hc066650294e3">+ Занятие</button><button class="g-btn danger" data-gym-click="hc3dd7adea88f">Отменить все занятия дня</button></div><div class="g-row"><button class="g-btn primary" data-busy="date-publish" data-gym-click="he43c7ae59fa7">Проверить и опубликовать</button><button class="g-btn" data-busy="date-publish" data-gym-click="hf359a6c7babd">Вернуть обычное расписание</button></div></div></section>`);
document.getElementById('community-date-class').innerHTML=(state.structure.classes||['11А','11Б','11В','11Г','11Д','11Ж']).map(cls=>`<option>${toolsEsc(cls)}</option>`).join('');
['community-date-class','community-date-edit'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{community.dateEditor=null;document.getElementById('community-date-body').hidden=true;}));
async function communityLoadDate(){await toolsRun('date-load',async()=>{const cls=document.getElementById('community-date-class').value,day=document.getElementById('community-date-edit').value;if(!day)return toolsToast('Выберите дату');const data=await toolsRequest('/api/admin/schedule/date?'+new URLSearchParams({class_name:cls,date:day}));if(cls!==document.getElementById('community-date-class').value||day!==document.getElementById('community-date-edit').value)return;community.dateEditor=data;document.getElementById('community-date-note').value=data.note;document.getElementById('community-date-body').hidden=false;document.getElementById('community-date-caption').textContent=`${cls} · ${communityParseDate(day).toLocaleDateString('ru-RU')} · ${data.is_override?'Изменения на дату':'Обычный учебный день'}`;communityRenderDateRows();});}
function communityRenderDateRows(){const data=community.dateEditor;if(!data)return;const fields=[['lesson_number','Номер','number'],['subject','Предмет','text'],['teacher_name','Учитель','text'],['cabinet','Кабинет','text'],['start_time','Начало','time'],['end_time','Конец','time'],['subgroup','Группа (пусто — все)','number'],['note','Примечание','text']];document.getElementById('community-date-rows').innerHTML=data.rows.map((row,index)=>`<details class="g-card" open><summary>${row.lesson_number} · ${toolsEsc(row.subject||'Новое занятие')}</summary><div class="g-date-row-fields">${fields.map(([key,label,type])=>`<label class="g-label">${label}<input class="g-input" type="${type}" value="${toolsEsc(row[key]??'')}" aria-label="${label}, замена ${index+1}" data-gym-change="h989dac62a32b" data-gym-args="${encodeURIComponent(JSON.stringify([(index),(key)]))}"></label>`).join('')}<label class="g-label">Профиль<select class="g-input" data-gym-change="h48020fde3b12" data-gym-args="${encodeURIComponent(JSON.stringify([(index)]))}"><option value="">Весь класс</option>${(state.structure.class_profiles?.[data.class_name]||[]).map(profile=>`<option ${row.profile_name===profile?'selected':''}>${toolsEsc(profile)}</option>`).join('')}</select></label></div><button class="g-btn danger" data-gym-click="h5f48fdd96c2a" data-gym-args="${encodeURIComponent(JSON.stringify([(index)]))}">Удалить занятие</button></details>`).join('')||'<p class="g-note">На эту дату не будет занятий. Проверьте дату перед публикацией.</p>';}
function communityEditDateRow(index,key,value){if(['lesson_number','subgroup'].includes(key))value=value===''?null:Number(value);if(['profile_name','start_time','end_time','note'].includes(key)&&value==='')value=null;community.dateEditor.rows[index][key]=value;}
function communityAddDateRow(){if(!community.dateEditor)return;const day=communityParseDate(community.dateEditor.date);if(day.getDay()===0)return toolsToast('Выберите учебный день');community.dateEditor.rows.push({day_of_week:day.getDay()-1,lesson_number:1,subject:'',teacher_name:'',cabinet:'',profile_name:null,subgroup:null,start_time:null,end_time:null,note:null});communityRenderDateRows();}
function communityCancelDay(){if(!community.dateEditor)return;community.dateEditor.rows=[];document.getElementById('community-date-note').value='Занятия отменены';communityRenderDateRows();}
async function communityPublishDate(reset){if(!community.dateEditor)return;const data=community.dateEditor;const description=reset?'Вернуть обычное расписание':data.rows.length?`Опубликовать ${data.rows.length} занятий`:'ОТМЕНИТЬ ВСЕ ЗАНЯТИЯ';if(!await communityConfirm(`${description} для ${data.class_name} на ${communityParseDate(data.date).toLocaleDateString('ru-RU')}? Другие даты сохранятся.\n\n${reset?'':data.rows.map(row=>`${row.lesson_number}. ${row.subject} · ${row.profile_name||'весь класс'} · каб. ${row.cabinet||'—'} · ${row.start_time||'по звонкам'}${row.end_time?'–'+row.end_time:''}`).join('\n')}`))return;await toolsRun('date-publish',async()=>{community.dateEditor=await toolsRequest('/api/admin/schedule/date'+(reset?'/reset':''),reset?'POST':'PUT',{class_name:data.class_name,date:data.date,rows:reset?[]:data.rows,note:document.getElementById('community-date-note').value,base_revision:data.base_revision});await communityLoadDate();await loadSchedule();await updateLiveScheduleStatus();toolsToast('Расписание на дату обновлено');});}
Object.assign(window,{loadNews,renderNewsPost,switchTab,toolsNewsTab,toolsToday,communityToday,communityScheduleDate,communityDateLabel});
communityRoleUI();
