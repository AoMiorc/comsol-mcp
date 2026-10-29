"""Native 220x220 benchmarks; --solve runs only the connected structured mask."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union
from smoothmeta import load_spec, prepare_geometry, export_geometry
from smoothmeta.preview import comparison


def example_masks():
    # Coordinates are specified on the native 220 grid, not an enlarged 9x9 mask.
    a = np.ones((220, 220), dtype=np.uint8)
    a[29:177, 37:171] = 0
    a[29:79, 37:92] = 1
    a[129:177, 136:171] = 1
    a[94:107, 37:121] = 1
    y, x = np.indices((220, 220))
    disk = (((x-108)**2 + (y-114)**2) < 83**2).astype(np.uint8)
    checker = ((x+y) % 2).astype(np.uint8)
    return dict(structured_220=a, disk_220=disk, checkerboard_220=checker)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--solve', action='store_true')
    p.add_argument('--output', default='runs/exact-v2')
    args = p.parse_args(); out = Path(args.output)
    if out.exists() and any(out.iterdir()): p.error('Choose a new output directory')
    out.mkdir(parents=True, exist_ok=True)
    results = []; rows = []
    for name, a in example_masks().items():
        print('Preparing '+name, flush=True)
        result = prepare_geometry(a, period_nm=550.)
        # Independent baseline: one box per occupied pixel, integer coordinates.
        start = time.perf_counter()
        ref = unary_union([box(int(x), int(y), int(x)+1, int(y)+1) for y, x in np.argwhere(a)])
        reference_seconds = time.perf_counter()-start
        from shapely.affinity import scale
        ref_nm = scale(ref, xfact=2.5, yfact=2.5, origin=(0, 0))
        error = result['geometry'].symmetric_difference(ref_nm).area
        if error != 0: raise RuntimeError('Independent pixel baseline differs')
        export_geometry(result, out/name)
        spec = dict(encoding=a.tolist(), geometry=dict(period_nm=550.), solver={})
        (out/(name+'.json')).write_text(json.dumps(spec), encoding='utf8')
        rows.append(dict(case=name, **result['metadata'], reference_pixel_union_seconds=reference_seconds,
                         independent_symmetric_difference_nm2=error))
        if name != 'checkerboard_220': results.append(result)
        print(json.dumps(rows[-1]), flush=True)
        (out/'benchmark.json').write_text(json.dumps(rows, indent=2), encoding='utf8')
    comparison(results, out/'comparison.png')
    if args.solve:
        from smoothmeta.comsol import evaluate_design
        spec = load_spec(out/'structured_220.json')
        report = evaluate_design(spec, out/'structured_comsol')
        print(json.dumps(dict(status=report['status'], points=report['points'])), flush=True)
    print('Outputs: '+str(out.resolve()), flush=True)


if __name__ == '__main__': main()
