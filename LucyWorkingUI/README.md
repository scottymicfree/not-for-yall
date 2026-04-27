# Lucy Working UI

A fresh local shell with:
- working prompt editor
- preloaded master build prompt
- Emma watcher panel
- Planetary Pulse starter panel
- checkpoint-based learning rewrite loop
- DeltaVault-style append-only ledger
- rewrite artifacts written to `data/workspace/live-lucy/rewrites`

## Run

Open `scripts/START_LUCY_UI.bat` on Windows.

This app uses plain Node.js and no package install is required.

## Main flow

1. Edit or paste the master build prompt
2. Click **Save Prompt**
3. Set loop count and checkpoint seconds
4. Click **Start Learning Loop**
5. Lucy reaches checkpoints, Emma reviews outcomes, and approved rewrites are written to versioned folders

## What is real

- prompt editing and saving
- local state persistence
- append-only ledger
- loop execution
- Emma review events
- real rewrite artifact files

## What is still a starter

- Earth feeds are modeled, not live-ingested
- rewrite artifacts are structured starter files, not full source rewrites
- Planetary Pulse is a data model + UI starter here, not full sonification yet
