"""Generate reproducible manifests without COMSOL."""
import copy,json,random,sys
from pathlib import Path

def generate(folder):
    root=Path(folder).resolve();root.mkdir(parents=True,exist_ok=True)
    def case(name,a,levels,smoke=False):
        return {'case_id':name,'template':'height_array_eigenmode',
          'geometry':{'rows':len(a),'cols':len(a[0]),'pillar_width_nm':100,'pitch_nm':150,
            'height_levels_nm':levels,'encoding':a,'air_nm':600 if smoke else 750,'substrate_nm':400 if smoke else 500,'pml_nm':300 if smoke else 400},
          'tuning':{'parameter':'height_offset_nm','values':[0,10]},
          'study':{'type':'eigenfrequency','search_frequency_THz':335,'number_of_modes':4 if smoke else 6},
          'mesh':{'level':7 if smoke else 5},'runtime':{'cores':4,'timeout_seconds':900 if smoke else 1800,'version':'6.4'}}
    small=[[0,1,0],[0,0,1],[1,0,1]]
    smoke={'cases':[case('smoke_asymmetric',small,[100,200],True),case('smoke_mirror',[r[::-1] for r in small],[100,200],True),case('smoke_uniform',[[0]*3 for _ in range(3)],[150],True)]}
    rng=random.Random(20261028);a=[[-1]*9 for _ in range(9)]
    for y in range(9):
        for x in range(9):
            if a[y][x]>=0:continue
            bit=rng.randrange(2);xx,yy=x,y
            for _ in range(4):a[yy][xx]=bit;xx,yy=8-yy,xx
    mean=100+100*sum(map(sum,a))/81
    full={'cases':[case('code9_asymmetric',a,[100,200]),case('code9_mirror',[r[::-1] for r in a],[100,200]),case('code9_uniform',[[0]*9 for _ in range(9)],[mean])]}
    for name,value in [('smoke_3x3.json',smoke),('example_9x9.json',full)]:
        (root/name).write_text(json.dumps(value,indent=2),encoding='utf8')
    (root/'build_9x9.json').write_text(json.dumps({'cases':[full['cases'][0]]},indent=2),encoding='utf8')
    acceptance=copy.deepcopy(full['cases'][0]);acceptance['case_id']='acceptance_9x9'
    acceptance['mesh']['level']=7;acceptance['tuning']['values']=[0]
    (root/'acceptance_9x9.json').write_text(json.dumps({'cases':[acceptance]},indent=2),encoding='utf8')
    print(root)

if __name__=='__main__':generate(sys.argv[1])
