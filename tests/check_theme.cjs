const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const storage = new Map();
function fixture(id, initData = 'signed') {
  const events = {}, properties = new Map(), classes = new Set();
  const root = {dataset:{},style:{setProperty:(k,v)=>properties.set(k,v),removeProperty:k=>properties.delete(k)},classList:{toggle:(k,v)=>v?classes.add(k):classes.delete(k)}};
  const app = {initData,initDataUnsafe:{user:{id}},colorScheme:'light',themeParams:{},onEvent:(k,f)=>events[k]=f,isVersionAtLeast:()=>true,setBackgroundColor(){},setHeaderColor(){},setBottomBarColor(){}};
  const system = {matches:false,addEventListener:(k,f)=>events.system=f};
  const window = {Telegram:{WebApp:app},matchMedia:()=>system,dispatchEvent(){}};
  vm.runInNewContext(fs.readFileSync('static/theme.js','utf8'),{window,document:{documentElement:root},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},CustomEvent:function(){}});
  return {app,window,events,properties,classes,root,system};
}
let f = fixture(1);
assert.equal(f.window.GymTheme.getMode(),'auto');
assert(!f.classes.has('dark'));
f.app.colorScheme='dark';f.events.themeChanged();assert(f.classes.has('dark'));
f.window.GymTheme.setMode('light');assert(!f.classes.has('dark'));
f.events.themeChanged();assert(!f.classes.has('dark'));
f.window.GymTheme.setMode('dark');assert(f.classes.has('dark'));
f.app.themeParams={bg_color:'#abcdef',text_color:'url(evil)'};
f.window.GymTheme.setMode('auto');assert.equal(f.properties.get('--g-bg'),'#abcdef');assert(!f.properties.has('--g-text'));
f.window.GymTheme.setMode('light');assert(!f.properties.has('--g-bg'));
f.window.GymTheme.setMode('invalid');assert.equal(f.window.GymTheme.getMode(),'light');
assert.equal(fixture(1).window.GymTheme.getMode(),'light');
assert.equal(fixture(2).window.GymTheme.getMode(),'auto');
f=fixture(3,'');f.system.matches=true;f.events.system();assert(f.classes.has('dark'));
console.log('PASS: Telegram light/dark events, explicit overrides, automatic system fallback, safe theme colours, persistent per-user preference');
