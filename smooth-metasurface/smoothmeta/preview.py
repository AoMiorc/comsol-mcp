"""Diagnostic previews; no COMSOL import or JVM startup."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch
from .geometry import parts

def draw_geometry(ax,g,**kwargs):
    for p in parts(g):
        # Nonzero fill rule needs opposite shell/hole orientation.
        from shapely.geometry.polygon import orient
        p=orient(p,sign=1)
        coords=[];codes=[]
        for r in [p.exterior,*p.interiors]:
            c=list(r.coords);coords.extend(c);codes.extend([MPath.MOVETO]+[MPath.LINETO]*(len(c)-2)+[MPath.CLOSEPOLY])
        ax.add_patch(PathPatch(MPath(coords,codes),**kwargs))

def comparison(results,path):
    fig,axs=plt.subplots(2,len(results),figsize=(4.5*len(results),8),squeeze=False,layout='constrained')
    for col,r in enumerate(results):
        o=r['metadata']['settings'];L=o['period_nm']
        axs[0,col].imshow(r['encoding'],origin='lower',extent=[0,L,0,L],vmin=0,vmax=1,cmap='viridis',interpolation='nearest')
        axs[0,col].set_title(f"Input {r['encoding'].shape}: {r['metadata']['filled_pixels']} material pixels")
        ax=axs[1,col];draw_geometry(ax,r['geometry'],facecolor='#278d8e',edgecolor='#164f50',lw=.6)
        m=r['metadata'];ax.set_title(f"Final CAD footprint: {m['vertices_final']} vertices\nArea fraction {m['area_fraction']:.3f}; regions/holes {m['final_components_holes']}")
        for ax in axs[:,col]:ax.set(xlim=(0,L),ylim=(0,L),xlabel='x (nm)',ylabel='y (nm)',aspect='equal')
    fig.suptitle('Exact pixel-region compression: all real corners retained\nTop: native mask. Bottom: exported CAD footprint.',fontsize=14)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fig.savefig(path,dpi=170);plt.close(fig)
