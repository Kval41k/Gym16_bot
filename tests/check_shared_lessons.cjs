const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/features.js','utf8');
const context={state:{selectedDay:0,structure:{class_profiles:{'11А':['Соц-гум','Филологический'],'11В':['Инфотех','Инженерный'],'11Д':['Инфотех'],'Тест':['А','Б','В']}}},toolsLessonPhase:()=>'',toolsEsc:value=>String(value)};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function toolsMergeSharedLessons'),source.indexOf('loadSchedule = async function')),context);
const base={id:1,class_name:'11А',day_of_week:0,lesson_number:5,subject:'Физика',teacher_name:'Трухина Ю.В.',cabinet:'1/416',start_time:'12:25',end_time:'13:05',note:'',profile_name:'Соц-гум',subgroup:null};
const merge=rows=>context.toolsMergeSharedLessons(rows);
const pair=[base,{...base,id:2,profile_name:'Филологический',teacher_name:'Трухина Ю. В.'}];
const original=JSON.stringify(pair);
assert.equal(merge(pair).length,1);assert.equal(merge(pair)[0].profile_name,null);
assert.equal(JSON.stringify(pair),original,'Source rows must remain unchanged for filtering and editing');
const html=context.renderLessonSlot({lesson_number:5,start_time:'12:25',end_time:'13:05',lessons:pair});
assert.equal((html.match(/<h3/g)||[]).length,1);assert(html.includes('Общий урок'));assert(!html.includes('Филологический'));
for(const change of [{teacher_name:'Другой учитель'},{cabinet:'3/109'},{start_time:'12:30'},{end_time:'13:10'},{subject:'Химия'},{note:'Контрольная'}])assert.equal(merge([base,{...pair[1],...change}]).length,2);
assert.equal(merge([{...base,teacher_name:''},{...pair[1],teacher_name:''}]).length,2);
const group={...base,class_name:'11Д',profile_name:'Инфотех',subgroup:1};
assert.equal(merge([group,{...group,id:3,subgroup:2}])[0].subgroup,null);
assert.equal(merge([group,{...group,id:3,subgroup:2,teacher_name:'Другой учитель'}]).length,2);
assert.equal(merge([{...base,class_name:'11В',profile_name:'Инфотех'},{...base,class_name:'11В',id:2,profile_name:'Инженерный'}]).length,1);
const incomplete=[{...base,class_name:'Тест',profile_name:'А'},{...base,class_name:'Тест',id:2,profile_name:'Б'}];
assert.equal(merge(incomplete).length,2,'Two out of three profiles must not become a class-wide lesson');
const diagonal=[{...base,subgroup:1},{...pair[1],subgroup:2}];assert.equal(merge(diagonal).length,2);
const grid=pair.flatMap(row=>[1,2].map(subgroup=>({...row,subgroup})));
assert.equal(merge(grid).length,1);assert.equal(merge(grid)[0].profile_name,null);assert.equal(merge(grid)[0].subgroup,null);
if(process.argv[2]) {
 const days=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 let joined=0;
 for(const day of days)for(const slot of day.slots){const rows=merge(slot.lessons);if(rows.length<slot.lessons.length){joined+=slot.lessons.length-rows.length;console.log(`${day.class_name} day ${day.day_of_week} lesson ${slot.lesson_number}: ${slot.lessons.length} → ${rows.length} (${rows.map(r=>r.subject).join(', ')})`);}}
 console.log(`Live timetable audit: ${joined} duplicate display rows combined across all classes`);
}
console.log('PASS: shared lessons render once, teacher/room/time/note differences preserved, incomplete audiences kept separate, source data unchanged');
