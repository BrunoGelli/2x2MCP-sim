# larnd-sim container dependency recovery

## Scope

This note documents a container regression encountered while processing the
first realistic Pythia-derived MCP sample through larnd-sim on Perlmutter.

The detector input itself was healthy. The failure occurred before larnd-sim
could begin detector response and was caused by Python dependency churn inside
the ephemeral Podman environment.

The important conclusion is:

> The known-good solution does **not** require rebuilding CUDA, Numba, or
> llvmlite from source. The working recipe is the same lightweight Python/CUDA
> overlay used by the earlier frozen baseline, provided that the pinned
> `larpix-control` reinstall is performed with `--no-deps`.

---

## Environment anchor

The GPU container remains:

```text
docker.io/mjkramer/sim2x2:ndlar011
```

The launcher mounts the NERSC CUDA 12.2 tree and uses the persistent larnd-sim
checkout:

```text
software/larnd-sim-current
```

Pinned larnd-sim commit:

```text
3b6449466e1e8036413ad9c6750b04a68515aea3
```

Pinned `larpix-control` commit:

```text
5a69050422e82356c8faf9ad0ea3168c322d63e8
```

The successful repaired environment observed the following core versions:

```text
NumPy        1.26.2
CuPy         12.2.0
Numba        0.67.0
llvmlite     0.49.0
numba-cuda   0.30.4
```

The `numba-cuda[cu12]` installation also supplied a newer pip-managed CUDA
runtime layer, including `libnvJitLink.so.12`. Its directory must precede the
mounted CUDA 12.2 libraries in `LD_LIBRARY_PATH`.

---

## Failure 1: NumPy 2.x broke CuPy

The original automated setup contained:

```bash
python -m pip install --force-reinstall \
    "git+https://github.com/larpix/larpix-control.git@${LARPIX_CONTROL_COMMIT}"
```

Because `--no-deps` was missing, pip re-resolved every `larpix-control`
dependency. In the failing launch it replaced the container's NumPy 1.26.2
with NumPy 2.4.6 and also reinstalled a large fraction of the Python stack.

CuPy then failed immediately during import:

```text
AttributeError: `np.float_` was removed in the NumPy 2.0 release.
Use `np.float64` instead.
```

The pip output itself also reported the incompatible requirement:

```text
cupy-cuda12x 12.2.0 requires numpy<1.27,>=1.20,
but numpy 2.4.6 was installed.
```

This was not an MCP, EDepSim, HDF5, GPU-allocation, or larnd-sim physics
problem. It was a package-resolution regression introduced by setup.

---

## Failure 2: repairing NumPy in place exposed a damaged Numba/llvmlite state

Downgrading only NumPy back to 1.26.2 restored CuPy and a simple CuPy GPU test,
but larnd-sim then failed while importing `numba.cuda`:

```text
AttributeError:
.../llvmlite/binding/libllvmlite.so:
undefined symbol: LLVMPY_CreatePassManager
```

At that point:

```text
NumPy      1.26.2
CuPy       12.2.0
Numba      0.67.0
llvmlite   0.49.0
```

looked superficially correct and `pip check` reported no broken requirements.
However, the earlier force reinstall had already replaced binary packages in
`/opt/venv`. `pip check` validates declared package requirements, not ABI
consistency of already-loaded/shared binary libraries.

The correct response was **not** additional in-place package surgery.

Because the container is launched with `--rm`, `/opt/venv` is disposable.
The reliable recovery is:

1. fix the persistent setup script under `$SCRATCH`;
2. exit the contaminated Podman container;
3. relaunch from the pristine base image;
4. let the known-good overlay be recreated in the correct order.

---

## Known-good installation order

The working hand-tested sequence is:

```bash
source /opt/environment

export CUDA_HOME=/opt/cuda/cuda/12.2
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="/opt/cuda/math_libs/12.2/targets/x86_64-linux/lib:$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"

python -m pip install --upgrade 'numba-cuda[cu12]'
```

Then find pip's `nvJitLink` library and prepend it:

```bash
NVJITLINK_DIR="$(
    find /opt/venv \
      -type f \
      -name 'libnvJitLink.so.12' \
      -printf '%h\n' \
      -quit 2>/dev/null
)"

export LD_LIBRARY_PATH="${NVJITLINK_DIR}:${LD_LIBRARY_PATH}"
```

Install only the pinned LArPix code, without allowing pip to touch its
transitive dependencies:

```bash
python -m pip install \
    --upgrade \
    --force-reinstall \
    --no-deps \
    "git+https://github.com/larpix/larpix-control.git@5a69050422e82356c8faf9ad0ea3168c322d63e8"
```

Finally install the pinned larnd-sim checkout:

```bash
cd "$SCRATCH/2x2_mcp/software/larnd-sim-current"
SKIP_CUPY_INSTALL=1 python -m pip install -e .
```

No CUDA compiler rebuild and no source rebuild of Numba/llvmlite is part of
this recipe.

---

## Why `--no-deps` is mandatory here

`larpix-control` itself is pinned because larnd-sim needs the LArPix packet/API
state at that commit. We are **not** using its package metadata to define the
whole container environment.

Therefore:

```text
--force-reinstall --no-deps
```

means exactly what we want:

```text
replace larpix-control code
leave NumPy / Numba / llvmlite / CuPy / CUDA overlay untouched
```

Removing `--no-deps` turns the LArPix hotfix into an uncontrolled environment
upgrade and must be treated as unsafe.

---

## Automated validation

The repository now includes:

```text
scripts/validate_larnd_container.sh
```

The setup script runs it before declaring the environment ready. It can also be
run manually inside the GPU container:

```bash
bash "$MCP2X2_ROOT/scripts/validate_larnd_container.sh"
```

The validator checks:

- `simulate_pixels.py` is installed;
- the larnd-sim checkout is at the pinned commit;
- NumPy remains compatible with CuPy 12.2 (`numpy < 1.27`);
- CuPy imports and executes a real GPU operation;
- `numba.cuda` imports;
- Numba reports CUDA available;
- a small `@cuda.jit` kernel compiles and executes on the GPU;
- `Packet_v2` and `Packet_v3` import from the pinned LArPix installation;
- `pip check` succeeds;
- the `simulate_pixels.py` CLI imports successfully.

A setup is not considered ready until this script prints:

```text
CONTAINER VALIDATION: PASS
```

---

## Submodule checkout hardening

A Git submodule's `.git` entry may be a file rather than a directory. The setup
script therefore no longer requires:

```bash
[[ -d "$LARND_DIR/.git" ]]
```

Instead it asks Git directly:

```bash
git -C "$LARND_DIR" rev-parse --is-inside-work-tree
```

This is safe for normal clones and for submodule work trees restored by:

```bash
git submodule update --init --recursive
```

---

## Manifest caveat discovered during this incident

The historical file:

```text
freeze/2026-08-17_working_baseline/manifests/larnd_container_pip_freeze.txt
```

currently records a NumPy 2.4.6 state alongside CuPy 12.2.0. That combination
is not the actual known-good runtime for this container and should **not** be
used as a version-lock file.

Treat that file as a historical capture of a mutated environment, not as the
canonical dependency specification.

The setup script now writes a timestamped runtime `pip freeze` only **after**
the GPU validator succeeds. A future cleanup should either replace the old
manifest with a deliberately version-locked core environment or build a
derived container with a recorded digest.

---

## Operational rule

If a future setup run starts uninstalling/reinstalling NumPy, Numba, llvmlite,
CuPy, SciPy, matplotlib, or a large unrelated dependency set while installing
the pinned LArPix hotfix, stop the container setup.

The expected LArPix reinstall should be small because it uses `--no-deps`.

If `/opt/venv` has already been substantially mutated, prefer:

```text
exit disposable container
        -> fix persistent script
        -> relaunch clean container
```

over trying to repair the ephemeral Python environment package-by-package.
