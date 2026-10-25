"""Independent assertions for the 11Б photo's pairs and subgroup swaps."""
import json
from pathlib import Path
rows=json.loads((Path(__file__).resolve().parents[1]/'data/11b_reviewed_20261025.json').read_text())['rows']
assert len(rows)==39
assert all(row['class_name']=='11Б' and row['profile_name'] is None for row in rows)
assert [len({r['lesson_number'] for r in rows if r['day_of_week']==d}) for d in range(6)]==[8,7,7,6,7,0]
def group(day,subgroup):
    return sorted([r for r in rows if r['day_of_week']==day and r['subgroup'] in (None,subgroup)],key=lambda r:r['lesson_number'])
assert [r['subject'] for r in group(0,1)]==['Разговоры о важном','История','История','Литература','Литература','Алгебра и начала математического анализа','Алгебра и начала математического анализа','Физика']
assert [r['subject'] for r in group(1,2)]==['Физика','Физика','Английский язык','Английский язык','Физическая культура','Физическая культура','Физика']
for g in (1,2):
    assert [r['subject'] for r in group(2,g)]==['Химия','Химия','Геометрия','Геометрия','География','География','ЭК Родной язык в жизни общества']
    assert [r['lesson_number'] for r in group(3,g)]==[1,2,3,4,5,6]
assert [r['subject'] for r in group(4,1)][4:6]==['Информатика и ИКТ','Английский язык']
assert [r['subject'] for r in group(4,2)][4:6]==['Английский язык','Информатика и ИКТ']
assert [(r['cabinet'],r['teacher_name']) for r in group(4,1)][4:6]==[('3/314','Тольянская В.В.'),('1/304','Мажникова В.Д.')]
assert [(r['cabinet'],r['teacher_name']) for r in group(4,2)][4:6]==[('3/111','Елохина М.В.'),('3/314','Тольянская В.В.')]
assert group(0,1)[0]['start_time']=='08:15' and group(0,1)[-1]['end_time']=='15:20'
assert len({(r['day_of_week'],r['lesson_number'],r['subgroup']) for r in rows})==39
print('PASS: 11Б photo, 39 rows / 35 periods, all pairs, exact Friday group swap, Thursday/Saturday empty cells and Monday clock')
