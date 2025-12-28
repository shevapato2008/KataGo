# Repository Guidelines

## Project Structure & Module Organization
- `cpp/` holds the C++ engine and backends; key subdirs include `core/`, `game/`, `neuralnet/`, `search/`, and `command/` for CLI subcommands.
- `python/` contains training scripts and the `python/katago/` package; the real-time API lives in `python/realtime_api/`.
- `cpp/tests/` contains C++ unit/regression tests and fixtures in `cpp/tests/data/`; `tests/` contains Python tests for the API.
- `docs/`, `images/`, and `misc/` provide documentation, diagrams, and auxiliary data.

## Build, Test, and Development Commands
- Build the engine (Linux example): `cd cpp && cmake . -DUSE_BACKEND=OPENCL && make -j$(nproc)`.
- Run the engine: `./katago gtp -model <MODEL>.bin.gz -config configs/gtp_example.cfg`.
- Benchmark performance: `./katago benchmark -model <MODEL>.bin.gz -config configs/gtp_example.cfg`.
- Start the real-time API: `PYTHONPATH=python python3 -m realtime_api.main`.
- Python dependencies: `pip install -r requirements.txt`.

## Coding Style & Naming Conventions
- C++ uses 2-space indentation and brace-on-same-line style; follow existing naming in `cpp/` (e.g., `CamelCase` types, `snake_case` locals).
- Python uses 4-space indentation with `snake_case` functions and `CamelCase` classes; keep modules in `python/katago/` consistent with current layout.
- Config files live under `cpp/configs/` and use `.cfg` naming.

## Testing Guidelines
- C++ core tests: `./katago runtests` (built binary required).
- Heavier NN-backed checks: `./katago runsearchtests` (requires a model and config).
- Python API tests: `pytest tests/test_realtime_api.py`.

## Commit & Pull Request Guidelines
- Prefer concise, present-tense commit messages; the history commonly uses conventional prefixes like `feat:`, `fix:`, `test:`, and `docs:`.
- PRs should describe the change, note backend/config impact, and list tests run.
- Avoid committing large model binaries; reference downloads or document where to obtain them.

## Configuration & Security Tips
- Engine configs live in `cpp/configs/`; copy and customize rather than editing examples in place.
- Real-time API settings use `config.yaml` in the repo root; keep secrets out of git and update the config template when adding variables.
