# Local COMSOL MCP development snapshot

This repository contains the current local development source and regression tests.

Based on https://github.com/wjc9011/COMSOL_Multiphysics_MCP at commit 0f6b2c5. The original LICENSE, citation metadata, and documentation are retained.

Generated simulation models, results, logs, Python caches, and local backup files are excluded. COMSOL manuals and knowledge databases are not bundled.

Local regression tests are in `local_tests/`.

## Encoded-height eigenmode batch extension

`comsol_batch/` provides a reusable Python library and CLI for encoded pillar arrays. `src/tools/batch.py` exposes the same implementation through five MCP tools. Restart the MCP service after deploying an updated source version.

Input examples are in `examples/encoded_eigenmodes/`. For example:

```bash
python -m comsol_batch validate examples/encoded_eigenmodes/smoke_3x3.json
python -m comsol_batch start examples/encoded_eigenmodes/smoke_3x3.json --output runs/smoke
python -m comsol_batch status runs/smoke
python -m comsol_batch collect runs/smoke
```

Validation on COMSOL 6.4: three 3x3 codes with two tuning points each returned 24 candidate eigenmodes; one 9x9 case returned six candidates on a complete 33,882-element mesh. Re-running the completed small batch reused its saved solutions. These are interface integration checks, not converged physical-mode or chirality results. PML/radiation-domain mode candidates remain unclassified.

License-free regression commands:

```bash
python -m unittest discover -s local_tests -p test_batch_api.py -v
python -m unittest discover -s local_tests -p test_solver_jobs.py -v
```

The 10 batch API tests and four isolated solver-job tests passed. Generated models, field solutions, and machine-specific run paths are not part of the source distribution.

