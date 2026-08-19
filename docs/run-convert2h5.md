# 3. Convert ROOT to HDF5

This stage converts selected EDepSim detector segments and truth into the larnd-sim input schema.

## Converter provenance

The worked sample used external `2x2_sim` commit:

```text
7c621864155483fa30d741a69481fafd8fbcb5a8
```

Verify:

```bash
export MCP2X2_ROOT="$SCRATCH/2x2_mcp"
export TWOBYTWO_SIM="$SCRATCH/2x2_sim"

git -C "$TWOBYTWO_SIM" rev-parse HEAD
```

Converter:

```text
$TWOBYTWO_SIM/run-convert2h5/convert_edepsim_roottoh5.py
```

## Select the active volume explicitly

```bash
export ARCUBE_ACTIVE_VOLUME=volTPCActive
```

Do not rely on a converter-version default. The EDepSim validation counted segments under `volTPCActive`, and the same container name must be selected here.

Confirm the converter behavior:

```bash
grep -n -E 'ARCUBE_ACTIVE_VOLUME|volTPCActive|volLArActive' \
  "$TWOBYTWO_SIM/run-convert2h5/convert_edepsim_roottoh5.py" \
  | head -n 30
```

## Define files

```bash
export ROOTFILE="$MCP2X2_ROOT/out/edep/mcp_020458GeV_q03_100evt_seed12345.root"
export RAW_H5="$MCP2X2_ROOT/out/edep/mcp_020458GeV_q03_100evt_seed12345.EDEPSIM.hdf5"
export CONVERTER="$TWOBYTWO_SIM/run-convert2h5/convert_edepsim_roottoh5.py"

test -s "$ROOTFILE" || { echo "Missing ROOT input"; exit 1; }
```

## Check Python dependencies

```bash
python - <<'PY'
import ROOT
import numpy
import h5py
import fire
import tqdm
print("ROOT :", ROOT.gROOT.GetVersion())
print("NumPy:", numpy.__version__)
print("h5py :", h5py.__version__)
print("converter environment: OK")
PY
```

## Run conversion

```bash
rm -f "$RAW_H5"

python "$CONVERTER" \
  --input_file "$ROOTFILE" \
  --output_file "$RAW_H5"
```

Do not use `--keep_all_dets` for this detector-response input. larnd-sim should receive the selected active-LAr segments, not all sensitive detectors in the full geometry.

### Known nonfatal warning

The current converter can emit a NumPy deprecation warning while assigning `pdg_id` from a one-element array. It did not affect the worked sample's counts or energy closure, but the converter should be modernized before a future NumPy upgrade turns the warning into an error.

## Inspect the raw converted file

```bash
python - "$RAW_H5" <<'PY'
import sys
import h5py
import numpy as np

fn = sys.argv[1]
with h5py.File(fn, "r") as f:
    print("Datasets:")
    for name in f:
        print(f"  {name:16s} {f[name].shape}")

    segments = f["segments"][:]
    trajectories = f["trajectories"][:]
    vertices = f["vertices"][:]

    print("vertices          :", len(vertices))
    print("trajectories      :", len(trajectories))
    print("segments          :", len(segments))
    print("unique vertex IDs :", len(np.unique(vertices["vertex_id"])))
    print("total dE [MeV]    :", float(segments["dE"].sum()))

    for name in ("mc_hdr", "mc_stack"):
        print(f"{name:16s}:", len(f[name]) if name in f else "absent")
PY
```

Worked-reference result:

```text
vertices          97
trajectories      622
segments          1331
total dE          2323.42041 MeV
mc_hdr            0
mc_stack          0
```

Particle populations:

| Dataset | e- | gamma | MCP |
|---|---:|---:|---:|
| Segments | 820 | 60 | 451 |
| Trajectories | 463 | 62 | 97 |

The 97 vertices match the 97 EDepSim events with at least one selected active-volume segment. The converter is not the generated-event denominator.

## Preserve the raw file and make a larnd input copy

```bash
export LARND_IN="$MCP2X2_ROOT/out/edep/mcp_020458GeV_q03_100evt_seed12345.LARNDINPUT.hdf5"

sha256sum "$RAW_H5"
command cp -p -f "$RAW_H5" "$LARND_IN"
```

Delete only zero-length non-GENIE truth datasets in the copy:

```bash
python - "$LARND_IN" <<'PY'
import sys
import h5py

fn = sys.argv[1]
with h5py.File(fn, "r+") as f:
    for name in ("mc_hdr", "mc_stack"):
        if name not in f:
            continue
        n = len(f[name])
        if n != 0:
            raise RuntimeError(
                f"Refusing to delete non-empty {name}: {n} rows"
            )
        print("Deleting zero-length dataset:", name)
        del f[name]
PY
```

!!! danger "Safety rule"
    Never delete non-empty `mc_hdr` or `mc_stack`. A sample with real populated generator truth requires those datasets.

## Validate the clean larnd input

```bash
python - "$LARND_IN" <<'PY'
import sys
import h5py

with h5py.File(sys.argv[1], "r") as f:
    assert "mc_hdr" not in f
    assert "mc_stack" not in f
    assert len(f["vertices"]) == 97
    assert len(f["trajectories"]) == 622
    assert len(f["segments"]) == 1331
    print("vertices     :", len(f["vertices"]))
    print("trajectories :", len(f["trajectories"]))
    print("segments     :", len(f["segments"]))
print("LARND INPUT: PASS")
PY

sha256sum "$RAW_H5" "$LARND_IN"
```

The hashes must differ because two HDF5 objects were removed. Keep both files.
