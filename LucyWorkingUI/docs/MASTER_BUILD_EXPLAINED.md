# Lucy Master Build Explained

This UI is for placing the master build prompt and then running the learning rewrite loop.

## Core doctrine

- Lucy runs by default.
- Emma watches by default.
- Emma approves safe rewrites.
- Emma blocks only on unsafe outcomes or protected-boundary violations.

## Loop behavior

- A loop reaches a checkpoint.
- Emma reviews the actual outcome.
- If approved, Lucy writes a real rewrite artifact.
- Lucy starts the next loop.

## Earth-first

Planetary Pulse is included as a first-class Earth-facing module.
