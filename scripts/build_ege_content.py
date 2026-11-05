"""Build the reviewed authored exam bank while preserving stable material source keys."""
import json
import os
from pathlib import Path
import runpy
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
for subject in ('math','russian'):
    runpy.run_path(str(ROOT/'scripts'/f'build_{subject}_exam_expanded.py'),run_name='__main__')
parts=[json.loads((ROOT/'data'/f'{subject}_exam_expanded.json').read_text()) for subject in ('math','russian')]
catalog=json.loads((ROOT/'data/ege_2027.json').read_text())
catalog.update(version='ege-2027-20261105-v2',checked_at='2026-11-05',notice='Нумерация по проекту ФИПИ-2027. Полные авторские памятки и экзаменационные прототипы, не официальные КИМ. Краткие ответы проверяются автоматически; развёрнутые решения и сочинения — через эталон и самопроверку без экспертной оценки.',topics=[topic for part in parts for topic in part['topics']])
questions=[q for part in parts for q in part['questions']]
from build_exam_graphs import attach_figures
attach_figures(questions)
assert len(catalog['topics'])==47 and len(questions)==470
for name,data in [('ege_2027.json',catalog),('practice_2027.json',{'version':'practice-2027-20261105-v2','questions':questions})]:
    (ROOT/'data'/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print('Built 47 guides and 470 authored exam prototypes')
