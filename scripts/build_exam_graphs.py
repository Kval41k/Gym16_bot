"""Supplement graphical exam prototypes with reproducible, accessible SVG figures."""
import html
import json
import math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def graph(name, curves, bounds, points=(), label='f(x)'):
    x0,x1,y0,y1=bounds;w,h=480,320;l,r,t,b=42,22,22,36
    X=lambda x:l+(x-x0)/(x1-x0)*(w-l-r)
    Y=lambda y:h-b-(y-y0)/(y1-y0)*(h-t-b)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="График {html.escape(label)}"><rect width="480" height="320" rx="16" fill="#fff"/><defs><clipPath id="plot"><rect x="{l}" y="{t}" width="{w-l-r}" height="{h-t-b}"/></clipPath></defs>']
    for x in range(math.ceil(x0),math.floor(x1)+1):
        out.append(f'<path d="M{X(x):.2f} {t}V{h-b}" stroke="#e5e9ef"/>')
        if x:out.append(f'<text x="{X(x):.2f}" y="{min(max(Y(0)+20,t+16),h-10):.2f}" text-anchor="middle" fill="#475569" font-size="15">{x}</text>')
    step=max(1,math.ceil((y1-y0)/10))
    for y in range(math.ceil(y0/step)*step,math.floor(y1/step)*step+1,step):
        out.append(f'<path d="M{l} {Y(y):.2f}H{w-r}" stroke="#e5e9ef"/>')
        if y:out.append(f'<text x="{min(max(X(0)-8,30),w-r):.2f}" y="{Y(y)+5:.2f}" text-anchor="end" fill="#475569" font-size="15">{y}</text>')
    if y0<=0<=y1:out.append(f'<path d="M{l} {Y(0):.2f}H{w-r}" stroke="#64748b" stroke-width="1.5"/>')
    if x0<=0<=x1:out.append(f'<path d="M{X(0):.2f} {t}V{h-b}" stroke="#64748b" stroke-width="1.5"/>')
    for f,color in zip(curves,('#1478dc','#d34069')):
        d=[];previous=None
        for i in range(1001):
            x=x0+(x1-x0)*i/1000
            try:y=f(x)
            except (ValueError,ZeroDivisionError,OverflowError):previous=None;continue
            if not math.isfinite(y) or abs(y)>1e4:previous=None;continue
            command='M' if previous is None or abs(y-previous)>2*(y1-y0) else 'L'
            d.append(f'{command}{X(x):.2f} {Y(y):.2f}');previous=y
        out.append(f'<path d="{" ".join(d)}" fill="none" stroke="{color}" stroke-width="2.7" clip-path="url(#plot)"/>')
    for x,y in points:
        anchor='end' if X(x)>w-110 else 'start';offset=-7 if anchor=='end' else 7
        out.append(f'<circle cx="{X(x):.2f}" cy="{Y(y):.2f}" r="4" fill="#1478dc"/><text x="{X(x)+offset:.2f}" y="{max(t+16,Y(y)-9):.2f}" text-anchor="{anchor}" font-size="16" fill="#172033">({x}; {y})</text>')
    out.append(f'<text x="{w-23}" y="{h-10}" fill="#475569" font-size="16">x</text><text x="{l+8}" y="18" fill="#172033" font-size="16">{html.escape(label)}</text></svg>')
    folder=ROOT/'static/ege-graphs';folder.mkdir(exist_ok=True)
    (folder/(name+'.svg')).write_text(''.join(out))

SPECS={
 (12,1):([lambda x:-2*x+5],(-2,4,-4,10),[(-1,7),(3,-1)],'f(x)'),
 (12,2):([lambda x:2*(x-2)**2-3],(-1,5,-5,10),[(2,-3),(4,5)],'f(x)'),
 (12,3):([lambda x:24/x],(-8,8,-10,10),[(4,6)],'f(x)'),
 (12,4):([lambda x:6/(x-2)-1],(-3,8,-8,10),[(3,5)],'f(x)'),
 (12,5):([lambda x:4**x],(-2,3,-1,20),[(2,16)],'f(x)'),
 (12,6):([lambda x:math.log2(x)],(-1,10,-4,5),[(8,3)],'f(x)'),
 (12,7):([lambda x:x*x-4*x+5,lambda x:2*x-3],(-1,5,-4,10),[],'f(x), g(x)'),
 (12,8):([lambda x:abs(x-2),lambda x:4],(-4,8,-1,8),[],'f(x), g(x)'),
 (12,9):([lambda x:2*x+3],(-1,4,-1,12),[(1,5),(3,9)],'f(x)'),
 (12,10):([lambda x:x*x-2*x],(-2,5,-3,12),[],'f(x)'),
 (9,1):([lambda x:1-2*x],(-3,5,-9,8),[(-2,5),(4,-7)],'Касательная'),
 (9,2):([lambda x:.02*(x+3)*x*x*(x-2)*(x-5)],(-5,7,-8,15),[],'Знаки f′(x)'),
 (9,3):([lambda x:-.1*(x+4)*(x+1)*(x-3)],(-6,6,-10,10),[],'Знаки f′(x)'),
 (9,4):([lambda x:.12*(-x**3/3+x*x/2+2*x)],(-5,6,-6,6),[],'f(x)'),
 (9,7):([lambda x:-(x+2)*(x-5)],(-4,7,-10,15),[],'f′(x)'),
 (9,10):([lambda x:(x-1)**2*(x+3)],(-5,4,-10,20),[],'f′(x)'),
}

def attach_figures(questions):
    for q in questions:
        if q['subject_code']!='math':continue
        key=(q['task_number'],int(q['id'].rsplit('-',1)[1]))
        if key not in SPECS:continue
        name=f'math-{key[0]:02d}-{key[1]:02d}'
        graph(name,*SPECS[key])
        q['figure']='/static/ege-graphs/'+name+'.svg'
        q['figure_alt']='Координатный график к условию. Все необходимые числовые данные также приведены в тексте задания.'
