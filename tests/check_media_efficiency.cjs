const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const listeners={},revoked=[];let active=0,peak=0,calls=0,serial=0,domReady,intersect;
class TestURL extends URL {}
TestURL.createObjectURL=()=>`blob:fixture-${++serial}`;
TestURL.revokeObjectURL=value=>revoked.push(value);
const context={URL:TestURL,location:{origin:'https://school.test'},window:{Telegram:{WebApp:{initData:'test-proof'}},addEventListener:(type,fn)=>listeners[type]=fn},document:{addEventListener:(type,fn)=>domReady=fn},fetch:async(path,options)=>{
  assert.equal(options.headers['X-Telegram-Init-Data'],'test-proof');active++;peak=Math.max(peak,active);calls++;
  await new Promise(resolve=>setTimeout(resolve,1));active--;
  return {ok:true,blob:async()=>({type:'image/jpeg',size:10*1024*1024})};
}};
vm.createContext(context);vm.runInContext(fs.readFileSync('static/media.js','utf8'),context);
(async()=>{
  const images=Array.from({length:20},()=>({dataset:{}}));
  images.forEach((image,i)=>context.window.setProtectedImage(image,`/uploads/${i}.jpg`));
  for(let tick=0;tick<50&&images.some(image=>!image.dataset.protectedLoaded);tick++)await new Promise(resolve=>setTimeout(resolve,5));
  assert(images.every(image=>image.dataset.protectedLoaded));assert.equal(calls,20);assert(peak<=4,`Too many concurrent downloads: ${peak}`);
  assert.equal(revoked.length,17,'Cache must retain at most 32 MB');
  const same={dataset:{}};context.window.setProtectedImage(same,'/uploads/19.jpg');await new Promise(setImmediate);assert.equal(calls,20,'Reuse the cached blob');
  listeners.pagehide();assert.equal(revoked.length,20,'Release all retained blobs');
  assert(!context.window.protectedImageAttrs('https://tracker.invalid/photo.jpg').includes('tracker.invalid'));
  const lazy={dataset:{protectedSrc:'/uploads/lazy.jpg'}};
  context.IntersectionObserver=class {constructor(cb){intersect=cb;}observe(){}unobserve(){}};
  context.MutationObserver=class {observe(){}};
  context.document.documentElement={nodeType:1,matches:()=>false,querySelectorAll:()=>[lazy]};context.document.body={};
  domReady();assert.equal(calls,20,'Offscreen and hidden images should not download');
  intersect([{isIntersecting:true,target:lazy}]);await new Promise(resolve=>setTimeout(resolve,10));assert.equal(calls,21);assert(lazy.dataset.protectedLoaded);
  console.log('PASS: four concurrent image requests, bounded blob cache, reuse and private authorization');
})().catch(error=>{console.error(error);process.exitCode=1;});
