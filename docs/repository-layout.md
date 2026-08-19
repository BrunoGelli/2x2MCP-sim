# Repository Layout

## Top-level structure

```text
2x2_mcp/
├── README.md
├── PROJECT_CONTEXT.md
├── mkdocs.yml
├── .gitmodules
│
├── docs/                         # Human handbook source
│
├── generator/                    # Realistic Pythia flux model and validators
├── gun_tests/                    # Controlled GPS regression tools
├── configs/ndlar_flow/           # Project-owned Flow runtime overlays
├── scripts/                      # Container launch/setup/validation helpers
├── freeze/                       # Frozen baseline manifests and incident notes
│
├── software/
│   ├── edep-sim/                 # Pinned custom fork submodule
│   ├── edep-sim_build/           # Local ignored build tree
│   ├── edep-sim_install/         # Local ignored installation
│   ├── larnd-sim-current/        # Pinned submodule
│   └── flow/
│       ├── h5flow/               # Pinned submodule
│       ├── ndlar_flow/           # Pinned submodule
│       └── flow.venv/            # Local ignored runtime
│
├── out/                          # Generated products, ignored
└── log/                          # Runtime logs, ignored
```

## Documentation roles

| File/location | Role |
|---|---|
| `PROJECT_CONTEXT.md` | Dense canonical AI/code-agent handoff |
| `docs/` | Human operating manual and wiki source |
| `mkdocs.yml` | Navigation, theme, and Markdown configuration |
| `README.md` | Repository front door and historical frozen-baseline background |
| `generator/FLUX_MODEL_WORKFLOW.md` | Authoritative flux architecture |
| `generator/EMPIRICAL_RESAMPLING_V3.md` | Detailed current sampler algorithm |
| `generator/GEOMETRY_AUDIT.md` | Accepted-window versus global-face distinction |

## Generator directory

Important files:

```text
generator/build_pythia_flux_model.py
generator/sample_pythia_flux.py
generator/flux_model_empirical_v3.py
generator/flux_model_core.py
generator/flux_geometry.py
generator/validate_pythia_edep.py
```

Generated model and sample data belong in `out/`, not Git.

## Controlled gun directory

The `gun_tests/` sample is intentionally retained as a simple regression test. It should remain understandable without the realistic Pythia model.

## Config ownership

The upstream Flow submodule should remain clean. Project-specific data is tracked under:

```text
configs/ndlar_flow/data/
```

and copied into the submodule only at runtime.

## Freeze directory

The historical baseline stores:

- software-state manifests;
- checksums;
- dependency freezes;
- incident/recovery notes;
- patches documenting former local changes;
- references to large ignored artifacts.

Large ROOT/HDF5 files must not be committed.

## Naming convention used by the realistic sample

```text
mcp_<massGeV>_q<charge>_<events>evt_seed<seed>.<STAGE>.<extension>
```

Worked examples:

```text
mcp_020458GeV_100evt_seed12345.manifest.csv
mcp_020458GeV_q03_100evt_seed12345.root
mcp_020458GeV_q03_100evt_seed12345.EDEPSIM.hdf5
mcp_020458GeV_q03_100evt_seed12345.LARNDINPUT.hdf5
mcp_020458GeV_q03_100evt_seed12345.LARNDSIM.hdf5
mcp_020458GeV_q03_100evt_seed12345.FLOW.hdf5
```

For future production, include a production/shard ID so filenames remain unique across array jobs.
