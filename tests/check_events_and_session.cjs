const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/events.js','utf8');
const calls=[],listeners={};const document={addEventListener:(name,cb)=>listeners[name]=cb};
const c={document,headmanSaveAttendance:(...p)=>calls.push(p),togglePostReaction:(...p)=>calls.push(p),communitySetRole:(...p)=>calls.push(p),contactDeveloper:()=>calls.push('contact'),JSON,decodeURIComponent};vm.createContext(c);vm.runInContext(source,c);
function fire(type,key,parameters,value='late'){
 const el={value,parentElement:document,getAttribute:name=>name==='data-gym-'+type?key:name==='data-gym-args'?encodeURIComponent(JSON.stringify(parameters)):null};
 const event={target:el,preventDefault(){this.prevented=true;},stopPropagation(){this.cancelBubble=true;}};
 listeners[type](event);return event;
}
fire('change','h5ed9b24249b5',[17]);assert.deepEqual(calls.pop(),[17,'late']);
fire('click','h9324a72da623',[42,'❤️']);assert.deepEqual(calls.pop(),[42,'❤️']);
const event=fire('click','h21ecdc74c7b2',[]);assert(event.prevented&&event.cancelBubble);assert.equal(calls.pop(),'contact');
fire('click','constructor',[]);assert.equal(calls.length,0,'Unknown/prototype handlers cannot execute');
for(const file of ['app','events','session','headman','learning','community','features','admin-users'])new vm.Script(fs.readFileSync('static/'+file+'.js','utf8'),{filename:file});
(async()=>{
 const fields=[{id:'propose-title',type:'text',value:'Unsaved title'},{id:'password',type:'password',value:'SECRET'},{id:'propose-file',type:'file',value:'FILE'}];
 const store=new Map(),events={},winEvents={},boxes=[],buttons=[];
 function element(tag){const e={tag,children:[],className:'',append(...a){this.children.push(...a);},addEventListener(type,fn){this[type]=fn;},setAttribute(){},showModal(){boxes.push(this);},close(){},remove(){},focus(){},select(){}};if(tag==='button')buttons.push(e);return e;}
 const context={URL,Date,JSON,navigator:{clipboard:{writeText:async text=>calls.push(text)}},location:{href:'https://test/',origin:'https://test'},sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k),removeItem:k=>store.delete(k)},window:{Telegram:{WebApp:{initData:'SECRET_INITDATA',initDataUnsafe:{user:{id:17}},close:()=>calls.push('close')}},fetch:async()=>({status:401}),addEventListener:(n,fn)=>winEvents[n]=fn},document:{querySelectorAll:()=>fields,createElement:element,body:{append(){}},addEventListener:(n,fn)=>events[n]=fn}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('static/session.js','utf8'),context);
 await context.window.fetch('/api/me/preferences');await context.window.fetch('/api/me/preferences');assert.equal(boxes.length,1);
 const saved=store.get('gym16:unsaved:17');assert(saved.includes('Unsaved title'));assert(!saved.includes('SECRET'));assert(!saved.includes('FILE'));
 await buttons[0].click();assert(calls.pop().includes('Unsaved title'));
 buttons[1].click();assert.equal(calls.pop(),'close');
 console.log('PASS: delegated numeric/string parameters and this/event semantics, rejected unknown handlers, no inline executable code, 401 draft preservation/copy/close without credential persistence');
})().catch(e=>{console.error(e);process.exitCode=1;});
