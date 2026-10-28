/* Keep unsaved editor text in the current user's session, never credentials or files. */
(() => {
 const nativeFetch=window.fetch.bind(window);
 const uid=String(window.Telegram?.WebApp?.initDataUnsafe?.user?.id||'');
 const key='gym16:unsaved:'+uid;
 const allowed=/^(propose-|edit-|ege-form-|onboard-|tools-comment-|headman-menu-)/;
 let dirty=false,shown=false;
 function snapshot(){
  const fields={};
  document.querySelectorAll('input[id],textarea[id],select[id]').forEach(el=>{
   if(allowed.test(el.id)&&!['file','password','hidden'].includes(el.type)&&el.value)fields[el.id]=el.value;
  });
  return fields;
 }
 function preserve(force=false){
  if(!uid||(!force&&!dirty))return;
  try{sessionStorage.setItem(key,JSON.stringify({time:Date.now(),fields:snapshot()}));}catch{}
 }
 const asText=fields=>Object.entries(fields).map(([id,value])=>id+': '+value).join('\n\n');
 function show(titleText,bodyText,fields,expired){
  const box=document.createElement('dialog');box.className='g-editor';
  const title=document.createElement('h2');title.textContent=titleText;
  const text=document.createElement('p');text.textContent=bodyText;
  const backup=document.createElement('textarea');backup.className='g-input';backup.readOnly=true;backup.rows=8;backup.value=asText(fields);backup.setAttribute('aria-label','Сохранённый текст форм');
  const copy=document.createElement('button');copy.className='g-btn';copy.textContent='Скопировать текст';
  copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(backup.value);copy.textContent='Текст скопирован';}catch{backup.focus();backup.select();text.textContent='Текст выделен. Скопируйте его вручную перед закрытием.';}});
  const close=document.createElement('button');close.className='g-btn primary';close.textContent=expired?'Закрыть приложение':'Продолжить';
  close.addEventListener('click',()=>{if(expired){preserve(true);window.Telegram?.WebApp?.close();}else{box.close();box.remove();try{sessionStorage.removeItem(key);}catch{}}});
  box.append(title,text,backup,copy,close);document.body.append(box);box.showModal();
 }
 function expired(){
  preserve(true);if(shown)return;shown=true;
  show('Нужно обновить вход','Авторизация Telegram истекла. Скопируйте важный текст, затем закройте и заново откройте мини-приложение. Копия также сохранена в этой сессии.',snapshot(),true);
 }
 window.fetch=async(...args)=>{
  const response=await nativeFetch(...args);
  try{const url=new URL(typeof args[0]==='string'?args[0]:args[0].url,location.href);
   if(response.status===401&&url.origin===location.origin&&url.pathname.startsWith('/api/'))expired();
  }catch{}
  return response;
 };
 document.addEventListener('input',event=>{if(allowed.test(event.target.id||''))dirty=true;});
 window.addEventListener('pagehide',()=>preserve());
 document.addEventListener('DOMContentLoaded',()=>{
  if(!uid)return;
  try{
   const saved=JSON.parse(sessionStorage.getItem(key)||'null');
   if(!saved||Date.now()-saved.time>86400000){sessionStorage.removeItem(key);return;}
   if(Object.keys(saved.fields||{}).length)show('Текст незавершённых форм','Сохранена копия текста из предыдущего открытия. Можно скопировать её и продолжить редактирование. Текущие записи не заменены.',saved.fields,false);
  }catch{}
 });
})();
