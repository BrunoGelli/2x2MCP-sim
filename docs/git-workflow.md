# Git and Repository Workflow

## Parent repository versus submodules

The parent repository records exact submodule commit pointers. It does not preserve uncommitted edits inside a submodule.

```text
2x2MCP-sim parent
├── software/edep-sim             submodule
├── software/larnd-sim-current    submodule
├── software/flow/h5flow          submodule
└── software/flow/ndlar_flow      submodule
```

MCP-project-specific Flow configuration belongs under top-level:

```text
configs/ndlar_flow/
```

not as permanent uncommitted edits inside `software/flow/ndlar_flow`.

## Normal update

```bash
cd "$SCRATCH/2x2_mcp"

git status -sb
git fetch origin
git pull --ff-only origin feature/pythia-spectrum-input

git submodule sync --recursive
git submodule update --init --recursive
```

`--ff-only` prevents an accidental merge commit during an ordinary synchronization.

## When local parent changes exist

Inspect first:

```bash
git status -sb
git diff --stat
git diff
```

For temporary uncommitted work:

```bash
git stash push -u -m "local work before sync"
git fetch origin
git pull --ff-only origin feature/pythia-spectrum-input
git submodule update --init --recursive
```

Do not immediately pop the stash if the remote now contains the same changes. Inspect it:

```bash
git stash list
git stash show --stat --include-untracked stash@{0}
git stash show -p --include-untracked stash@{0}
```

Drop only after confirming it is redundant:

```bash
git stash drop stash@{0}
```

## Runtime Flow overlays and a dirty submodule

Installing project overlays makes `software/flow/ndlar_flow` intentionally dirty. Typical status:

```text
 M data/ndlar_flow/ndlar-module.yaml
 M data/proto_nd_flow/2x2.yaml
 M data/proto_nd_flow/runlist-2x2-mcexample.txt
?? data/proto_nd_flow/multi_tile_layout-2.4.16_v4.yaml
?? data/proto_nd_flow/multi_tile_layout-2.5.16_v4.yaml
```

This does not change the parent repository and does not mean the upstream code should be committed.

### Safe inspection

```bash
export NDLAR_DIR="$SCRATCH/2x2_mcp/software/flow/ndlar_flow"
git -C "$NDLAR_DIR" status --short
git -C "$NDLAR_DIR" diff --stat
```

### Selective cleanup after the run

```bash
git -C "$NDLAR_DIR" restore \
  data/ndlar_flow/ndlar-module.yaml \
  data/proto_nd_flow/2x2.yaml \
  data/proto_nd_flow/runlist-2x2-mcexample.txt

rm -f \
  "$NDLAR_DIR/data/proto_nd_flow/multi_tile_layout-2.4.16_v4.yaml" \
  "$NDLAR_DIR/data/proto_nd_flow/multi_tile_layout-2.5.16_v4.yaml"

git -C "$NDLAR_DIR" status --short
```

### Full destructive cleanup

!!! danger
    The following deletes **all** uncommitted and untracked content in the submodule. Use it only after confirming there is no unrelated work.

```bash
git -C "$NDLAR_DIR" reset --hard
git -C "$NDLAR_DIR" clean -fd
git submodule update --init --recursive
```

## Never casually update submodules to remote tips

Do not use this on a frozen or controlled state:

```bash
git submodule update --remote
```

It follows branch hints and can silently advance dependencies.

Restore the exact parent-pinned commits with:

```bash
git submodule update --init --recursive
```

## Check all repositories before a checkpoint

```bash
git status -sb
git submodule status
git submodule foreach --recursive \
  'echo; echo "[$name]"; git status --short'
```

## Shell pitfalls encountered during the worked run

### `cp` prompts despite no `-i`

An interactive shell alias can turn `cp` into `cp -i`. Bypass it in documented automation:

```bash
command cp -f SOURCE DESTINATION
```

### `echo #VARIABLE` prints nothing useful

`#` starts a shell comment. Use:

```bash
echo "$NDLAR_DIR"
```

not:

```bash
echo #NDLAR_DIR
```
