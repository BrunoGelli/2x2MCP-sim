# Troubleshooting

## First response checklist

Before changing packages or code, capture:

```bash
pwd
hostname
date

git status -sb
git log -1 --oneline
git submodule status

echo "$SCRATCH"
echo "$MCP2X2_ROOT"
```

Then identify the environment:

```text
normal host shell
Shifter CPU simulation shell
Podman larnd GPU shell
Flow virtual environment
```

Many historical failures came from running the right command in the wrong environment.

---

## Git and submodule problems

### Pull refuses because local files overlap

Inspect, then stash:

```bash
git status -sb
git diff --stat
git stash push -u -m "local work before sync"
git fetch origin
git pull --ff-only origin feature/pythia-spectrum-input
```

Inspect the stash before restoring it. It may contain an older copy of a fix that is now remote.

### `ndlar_flow` appears dirty after a successful run

Expected when runtime overlays were copied. See [Git and Repository Workflow](git-workflow.md). Do not commit the copied files inside the upstream submodule.

### Submodule `.git` is a file, not a directory

This is normal. Test a checkout with:

```bash
git -C PATH rev-parse --is-inside-work-tree
```

Do not require `PATH/.git` to be a directory.

### Parent commit does not preserve submodule edits

The parent records only the submodule commit SHA. Uncommitted submodule files must be committed in the submodule or copied into the parent as explicit overlays/patches.

---

## Generator problems

### Aggregate-summary audit fails

The selected ROOT inputs and aggregate CSV do not describe the same production totals.

Check:

- mass tolerance and selected mass;
- geometry ID;
- recursive input directory;
- production-mode keys;
- whether the aggregate summary was rebuilt after adding shards;
- `input_summary_audit.csv`.

Do not use `--allow-summary-mismatch` merely to get output. Use it only when the mismatch is understood and recorded.

### Central module gap is populated

The current accepted-stage v3 sampler should structurally protect the gap. Possible causes:

- an obsolete v2 model was loaded;
- a source-stage model was interpreted as accepted-stage;
- donor side labels or hard bounds changed;
- a plot is showing post-rotation detector-global coordinates rather than the Pythia conditioning coordinates.

Verify model type in `provenance.json`:

```text
weighted_empirical_donor_local_jitter_v3
```

### Beam points in the wrong direction

Expected on-axis transform:

```text
Pythia (0,0,+1) → 2x2 (0,-0.05826,+0.99830)
```

A dominant `-x` direction indicates an obsolete coordinate convention.

### Geometry consistency is below one

For an accepted-stage model this is a diagnostic, not a second acceptance. Review `generator/GEOMETRY_AUDIT.md`. The Pythia conditioning window and the post-rotation detector-global audit are not identical coordinate uses.

---

## EDepSim problems

### Wrong MCP mass or charge

Set environment variables before EDepSim initializes:

```bash
export EDEPSIM_MCP_MASS_MEV=20.458
export EDEPSIM_MCP_CHARGE=0.3
```

Confirm the log reports the intended values.

### Stock EDepSim runs instead of the custom build

```bash
which edep-sim
```

It must resolve under:

```text
$SCRATCH/2x2_mcp/software/edep-sim_install/bin
```

Prepend the local `bin` and `lib` paths inside the simulation environment.

### HEPEVT file cannot be found

The generated macro stores the path used at sampling time. For a relative path, run EDepSim from the project root. Inspect:

```bash
grep hepevt/input SAMPLE.mac
```

Regenerate the sample or edit a copied macro deliberately if the file moved.

### Fewer ROOT events than requested

The realistic macro must contain:

```text
/edep/db/set/requireEventsWithHits false
```

Without it, EDepSim can remove zero-hit events and corrupt the efficiency denominator.

### `volTPCActive is not found in /` appears before update

The command can be issued before geometry initialization and later becomes valid once the GDML is loaded and `/edep/update` runs. The worked sample completed and produced `volTPCActive` segments. Treat it as fatal only if the final ROOT file lacks the expected active-volume collection.

### Pythia→EDep validator fails

Stop the pipeline. Check:

- manifest and ROOT belong to the same sample;
- event ordering;
- unit conversions (`GeV→MeV`, `m→mm`);
- HEPEVT path and content;
- custom mass environment variable;
- coordinate rotation version.

Do not proceed to conversion until interface closure is restored.

---

## ROOT→HDF5 problems

### No segments are converted

Set:

```bash
export ARCUBE_ACTIVE_VOLUME=volTPCActive
```

Verify the converter supports the environment variable and that ROOT contains that detector collection.

### Converted vertices are fewer than generated events

Expected when an event has no selected active-volume segment. Preserve the generated denominator from the manifest/ROOT; do not infer it from HDF5 vertices.

### NumPy array-to-scalar deprecation warning

Nonfatal for the validated converter and NumPy 1.26 stack. The code should eventually extract the scalar explicitly. Revalidate if NumPy is upgraded.

### larnd-sim fails on `mc_hdr` shape

For non-GENIE input, the converter can create zero-length `mc_hdr` and `mc_stack`. Preserve the raw converted file, copy it, and delete only those datasets when their length is exactly zero.

---

## larnd container problems

### CuPy fails with `np.float_ was removed`

**Cause:** NumPy was upgraded to 2.x while CuPy 12.2 expects NumPy 1.x APIs.

The historical trigger was reinstalling `larpix-control` without `--no-deps`.

**Correct response:**

1. ensure the persistent setup script installs LArPix with `--no-deps`;
2. exit the disposable container;
3. relaunch from the clean base image.

Do not bless a repaired environment until `scripts/validate_larnd_container.sh` passes.

### `libllvmlite.so: undefined symbol LLVMPY_CreatePassManager`

This appeared after manually downgrading NumPy inside a container whose Numba/llvmlite stack had already been reinstalled by pip.

`pip check` can still say everything is fine because it does not detect shared-library ABI mismatch.

**Response:** discard the contaminated `--rm` container and relaunch using the corrected script. Do not compile Numba or CUDA.

### nvJitLink symbol/version failure

The modern Python CUDA overlay may require the pip-installed CUDA 12.9 `libnvJitLink.so.12`, while the mounted CUDA tree is 12.2.

The setup script finds and prepends the pip library directory. Verify the loaded API:

```bash
python - <<'PY'
from cuda.bindings import nvjitlink
print(nvjitlink.version())
PY
```

Worked result:

```text
(12, 9)
```

### `numba.cuda.core` or modern CUDA API missing

The base image contains an older Numba CUDA integration. The validated overlay is installed with:

```bash
python -m pip install --upgrade 'numba-cuda[cu12]'
```

Use the repository setup script rather than applying this ad hoc.

### `Packet_v3` missing

The base image's LArPix package is too old. The setup script installs the pinned `larpix-control` commit with `--no-deps` and validates both `Packet_v2` and `Packet_v3` imports.

### GPU visible to `nvidia-smi` but Python CUDA fails

Run the full validator. It tests both CuPy device execution and a Numba JIT kernel. Merely importing `numba` or seeing a GPU is not sufficient.

### `$SCRATCH` is empty inside the container

A bind mount does not automatically export the environment variable. Use `scripts/launch_larnd_container.sh`, which passes both the mount and `--env SCRATCH=...`.

### Container changes disappear on exit

Expected: the launcher uses `--rm`. Only `$SCRATCH` paths persist. Package overlays under `/opt/venv` are recreated on every launch.

---

## larnd-sim output problems

### Neutral segments are rejected

Expected for gamma segments in charge drift. The worked reference rejected 60 neutral segments and preserved `1271 = 1331-60` charge-relevant segments.

### No or very few data packets at `q=0.3e`

Unexpected for the worked high-charge sample. Check:

- clean input datasets;
- detector configuration `2x2_mpvmpr`;
- mass and charge used in EDepSim;
- segment energy and positions;
- threshold/pedestal map loading;
- module completion in the log.

### Output is hundreds of megabytes for only 100 events

The current configuration writes optical waveforms `(97,384,1000)`. This dominates storage. Charge-only production may later disable light, but that optimization is not yet validated.

---

## Flow problems and warnings

### `Running without mpi4py`

The small reference runs serially and succeeds. For production, choose serial sharding or install/test MPI deliberately.

### `Could not find row matching ... in runlist`

Flow uses MC defaults. The reference succeeded, but future production should add an explicit MCP runlist row or dedicated run-data configuration.

### `Using vertex_id instead of file_vertex_id`

Safe only when event IDs are unique in the input file. It is unsafe for naive merges of shards that each begin at vertex 0.

### `Hope you are not processing neutrino simulation`

Expected for an MCP-only file with no neutrino-interaction summary.

### scikit-learn `InconsistentVersionWarning`

A serialized `KernelDensity` estimator was created under 1.3.2 and loaded under 1.9.0. The reference completed, but production must pin the compatible version or regenerate the model.

### Channels use default threshold

Some channel IDs are absent from the threshold JSON. The fallback is nonfatal but is detector-response information. Record the fractions and evaluate their effect on efficiency.

### `cp` asks for overwrite confirmation

Your shell likely aliases `cp` to `cp -i`. Use:

```bash
command cp -f SOURCE DEST
```

---

## When to stop rather than patch forward

Stop and preserve logs when:

- identity or event ordering changes;
- the custom particle is not used;
- the geometry or software commit is unknown;
- the source-summary audit fails;
- the container validator fails;
- active-LAr ROOT/HDF5 closure fails;
- a workaround would delete non-empty truth;
- a production warning changes packet or event counts unexpectedly.

A partial, well-diagnosed run is more valuable than an undocumented output produced by accumulating local fixes.
