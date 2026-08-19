# Adopt Contribution Copilot on a real repository

The offline walkthrough stays in `demo/`. This folder is the generic
starting policy for a clone that is not the vLLM fixture.

```bash
mkdir -p .contrib-pilot
cp examples/config.toml .contrib-pilot/config.toml   # then edit allowlists
# or: uv run contrib-pilot init --path /path/to/the/repo
cp examples/issue.md path/to/issue.md                # then fill in the task
uv run contrib-pilot init --path /path/to/the/repo
```

`init` copies `examples/config.toml` only when `.contrib-pilot/config.toml`
is missing. It never overwrites an existing policy file. Check the copied
config into the target repository; `.contrib-pilot/runs/` stays gitignored.

Tighten `[context].allowed_sources` and `[changes].allowed_paths` to the
files this contribution may read and change before running `plan`.
