"""Plot the encoded geometry's measured modes and matched zero-kappa controls."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def analyze(folder):
    folder=Path(folder);rows=json.loads((folder/'results.json').read_text(encoding='utf8'))
    nominal=[];zero=[]
    field_data={}
    for i,r in enumerate(rows):
        candidates=[(j,m) for j,m in enumerate(r['modes']) if 333<m['real_THz']<337 and abs(m['imag_THz'])<.2 and m['slab_fraction']>.1]
        if len(candidates)!=2:raise RuntimeError('Ambiguous candidate pair '+str(r['thickness_nm']))
        item=dict(thickness_nm=r['thickness_nm'],modes=[m for j,m in candidates],indices=[j for j,m in candidates],source_row=i)
        f=np.load(folder/f'fields_{i+1:03d}.npz')['field']
        v=np.transpose(f,(1,0,2)).reshape(f.shape[1],-1)
        field_data[i]=v/np.linalg.norm(v,axis=1,keepdims=True)
        (zero if r['kk']=='0' else nominal).append(item)
    nominal.sort(key=lambda v:v['thickness_nm']);zero.sort(key=lambda v:v['thickness_nm'])
    fig,axs=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
    for b,color,label in [(0,'#d32f2f','Coupled LB'),(1,'#1765cb','Coupled UB')]:
        t=[r['thickness_nm'] for r in nominal]
        ms=[sorted(r['modes'],key=lambda m:m['real_THz'])[b] for r in nominal]
        axs[0].plot(t,[m['real_THz'] for m in ms],'o-',color=color,label=label)
        axs[1].plot(t,[m['ez_fraction'] for m in ms],'o-',color=color,label=label)
    for b,color,label in [(0,'#333333','Zero chirality: transverse-like'),(1,'#777777','Zero chirality: longitudinal-like')]:
        t=[r['thickness_nm'] for r in zero]
        ms=[sorted(r['modes'],key=lambda m:m['ez_fraction'])[b] for r in zero]
        style='x--' if len(zero)>2 else 'x'
        axs[0].plot(t,[m['real_THz'] for m in ms],style,color=color,label=label,ms=5)
        axs[1].plot(t,[m['ez_fraction'] for m in ms],style,color=color,label=label,ms=5)
    gaps=[dict(thickness_nm=r['thickness_nm'],separation_THz=abs(r['modes'][1]['real_THz']-r['modes'][0]['real_THz'])) for r in nominal]
    zero_gaps=[dict(thickness_nm=r['thickness_nm'],separation_THz=abs(r['modes'][1]['real_THz']-r['modes'][0]['real_THz'])) for r in zero]
    minimum=min(gaps,key=lambda r:r['separation_THz'])
    axs[0].annotate(f"Smallest sampled separation: {minimum['separation_THz']*1000:.2f} GHz",
        xy=(.03,.04),xycoords='axes fraction',fontsize=8)
    axs[0].set(xlabel='Slab thickness (nm)',ylabel='Real eigenfrequency (THz)',title='110 x 110 encoded geometry: measured branches')
    axs[1].set(xlabel='Slab thickness (nm)',ylabel='Slab integral |Ez|² / |E|²',title='Polarization character of the same pair')
    for ax in axs:ax.grid(alpha=.2)
    axs[0].legend(fontsize=7.5)
    fig.savefig(folder/'gap_scan.png',dpi=180);plt.close(fig)
    # Track the isolated two-mode subspace, robust to hybrid mode rotations near zero detuning.
    overlaps=[]
    for seq,name in [(nominal,'nominal'),(zero,'zero')]:
        for a,b in zip(seq,seq[1:]):
            va=field_data[a['source_row']][a['indices']];vb=field_data[b['source_row']][b['indices']]
            qa=np.linalg.qr(va.T)[0];qb=np.linalg.qr(vb.T)[0]
            singular=np.linalg.svd(qa.conj().T@qb,compute_uv=False)
            overlaps.append(dict(case=name,from_nm=a['thickness_nm'],to_nm=b['thickness_nm'],minimum_subspace_overlap=float(min(singular)**2)))
    matching=[]
    zero_by_t={r['thickness_nm']:r for r in zero}
    for a in nominal:
        if a['thickness_nm'] not in zero_by_t:continue
        z=zero_by_t[a['thickness_nm']]
        f=sorted(m['real_THz'] for m in a['modes']);g=sorted(m['real_THz'] for m in z['modes'])
        matching.append(dict(thickness_nm=a['thickness_nm'],nominal_separation_THz=f[1]-f[0],zero_separation_THz=g[1]-g[0]))
    report=dict(nominal=nominal,zero=zero,gaps=gaps,zero_gaps=zero_gaps,minimum_sampled_gap=minimum,matched_controls=matching,subspace_tracking=overlaps,
        warning='Sparse measured samples; exact minimum, coding resolution, mesh/PML convergence and analytical mode orders are not certified. Nonzero material kappa is imposed: this does not establish chirality from geometry alone.')
    (folder/'gap_analysis.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(minimum_sampled_gap=minimum,matched_controls=matching,minimum_subspace_overlap=min((r['minimum_subspace_overlap'] for r in overlaps),default=None)),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');analyze(p.parse_args().folder)
