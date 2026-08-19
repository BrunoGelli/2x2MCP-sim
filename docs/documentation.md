# Maintaining This Handbook

## Why MkDocs

The handbook is stored in the same repository as the simulation state. This provides a wiki-like site while keeping documentation reviewable, branchable, taggable, and available offline.

An external GitHub Wiki is not the canonical source because it is a separate Git repository and can drift from the code version it describes.

## Build locally

Create a documentation environment outside the project checkout:

```bash
python -m venv "$SCRATCH/.venvs/2x2mcp-docs"
source "$SCRATCH/.venvs/2x2mcp-docs/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$SCRATCH/2x2_mcp/docs/requirements.txt"
```

From the project root:

```bash
cd "$SCRATCH/2x2_mcp"
mkdocs build --strict
```

The generated static site appears under:

```text
site/
```

Do not commit `site/`; it is a build artifact.

## Preview interactively

```bash
mkdocs serve --dev-addr 127.0.0.1:8000
```

On a remote NERSC host, use SSH port forwarding appropriate to your connection setup before opening the local browser URL.

## Documentation authority

Update these together after a milestone:

1. machine-readable sample provenance;
2. `PROJECT_CONTEXT.md`;
3. the relevant handbook pages;
4. root `README.md` status/links when the public project summary changes;
5. frozen manifests and checksums when creating a baseline.

## Writing rules

### Label the state

Distinguish:

- validated current command;
- recommended safer command;
- historical command;
- planned/unverified procedure.

### Use exact units

Prefer:

```text
20.458 MeV
0.020458 GeV
0.0175775 MeV/mm
MCP/POT/epsilon^2
```

Do not omit unit conversions in cross-stage validators.

### Separate reference samples

Never place controlled-GPS and realistic-Pythia numbers in one unlabeled table.

### Explain workarounds

A command such as deleting `mc_hdr` is dangerous without its precondition. Document:

- the symptom;
- the root cause;
- the safety guard;
- what must never be deleted;
- the long-term fix.

### Preserve commands as executable blocks

Commands should define paths, check inputs, capture exit status, and show expected success criteria.

### Keep large output out of docs

Summarize logs and link to tracked notes or machine-readable manifests. Do not paste thousands of routine Geant4 or pip lines.

## Adding a page

1. Add `docs/<page>.md`.
2. Add it to `nav` in `mkdocs.yml`.
3. Link it from a relevant existing page.
4. Run:

```bash
mkdocs build --strict
```

5. Check all shell blocks and expected values against the current source/provenance.

## Optional GitHub Pages deployment

No deployment workflow is added by this documentation-only milestone. A later repository-management task can publish `mkdocs gh-deploy` or configure a GitHub Actions Pages workflow after deciding:

- deployment branch or Pages artifact mode;
- whether feature-branch docs should be public;
- permissions and repository settings;
- versioning strategy for historical baselines.

The Markdown remains fully usable without Pages.

## Review checklist after a pipeline change

- [ ] Did a file path or CLI change?
- [ ] Did a commit/configuration pin change?
- [ ] Did a new warning appear?
- [ ] Did stage counts or expected output size change?
- [ ] Did an approximation or physics limitation change?
- [ ] Is the change reflected in `PROJECT_CONTEXT.md`?
- [ ] Is the worked reference still valid?
- [ ] Does `mkdocs build --strict` pass?
