const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('static/headman.js','utf8');
assert(!source.includes('headman-class-label'));
assert(!source.includes('headmanChangeClass'));
const mealContext={};vm.createContext(mealContext);
vm.runInContext(source.slice(source.indexOf('function headmanMealOptions'),source.indexOf('function headmanRenderMeals')),mealContext);
assert.deepEqual(Array.from(mealContext.headmanMealOptions({options:{main:['Первое','Второе']}},'main')),['Первое','Второе']);
async function checkCopy(mode,legacyWorks=true){
 const writes=[],calls=[],status={textContent:''},command={textContent:'/class_link LOCAL_TEST_CODE'},input={style:{},setAttribute(){},focus(){},select(){},setSelectionRange(){},remove(){calls.push('remove');}};
 const context={navigator:{},toolsToast:message=>calls.push(message),document:{getElementById:id=>id==='headman-copy-command'?command:status,activeElement:{focus(){calls.push('restore-focus');}},createElement:()=>input,body:{append(){calls.push('append');}},execCommand:action=>{calls.push(action);return legacyWorks;}}};
 if(mode!=='missing')context.navigator.clipboard={writeText:async text=>{if(mode==='denied')throw Error('denied');writes.push(text);}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function headmanCopyCommand()')),context);
 await context.headmanCopyCommand();
 if(mode==='ok'){assert.deepEqual(writes,[command.textContent]);assert(!calls.includes('copy'));}
 else{assert(calls.includes('copy'));assert(calls.includes('remove'));assert(calls.includes('restore-focus'));}
 assert(status.textContent.includes(mode==='ok'||legacyWorks?'Команда скопирована':'вручную'));
}
(async()=>{await checkCopy('ok');await checkCopy('denied');await checkCopy('missing');await checkCopy('denied',false);console.log('PASS: class selector absent, meal offers two options, clipboard success/permission fallback/legacy fallback/manual failure are truthful');})().catch(error=>{console.error(error);process.exitCode=1;});
