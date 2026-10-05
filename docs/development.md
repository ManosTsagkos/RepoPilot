# Development checks

Install the Python development dependencies with the README's pip command. To reproduce the CI dependency versions instead, use `uv sync --locked --extra dev`; run Python commands below with the `uv run --locked --extra dev` prefix.

## Python and packaging

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The Python suite uses mocked upstream HTTP responses. It covers repository input, GitHub pagination and malformed responses, structured model output, demo routes, settings, cache eviction and expiry, concurrent and cancelled analyses, and local browser safeguards. It does not call GitHub or OpenAI.

Packaging tests are part of the normal pytest run. They copy the project to a temporary directory and build a source archive followed by a wheel from that archive. The development extra includes the build backend, so `--no-isolation` can build without fetching packages.

The archive check verifies that `.env.example`, lockfiles, development checks, and test fixtures survive distribution, while local `.env` files and caches do not. A second check installs the wheel with bundled pip into a temporary directory, then starts the installed app outside the checkout using the test environment's runtime dependencies. It verifies the demo routes and dashboard assets. This catches missing package data that an editable installation can hide.

To build release files yourself:

```sh
python -m build --no-isolation
```

The wheel contains the application, static assets, and demo dataset. The source archive also contains setup examples, documentation, tests, and lockfiles.

## Dashboard

Use a current Node.js 24 release; `package.json` lists other supported versions.

```sh
npm ci
npm run check
npm test
```

The Node test runner uses jsdom to exercise the real dashboard script against a local DOM and controlled responses. It complements the Python API tests; it does not replace checking the layout and interactions in a real browser. No JavaScript dependencies or build output are needed to serve the app.

## Continuous integration

The public browser demo is generated from the dashboard and sample dataset. After changing either, run `python scripts/build_demo.py`. `python scripts/build_demo.py --check` detects stale committed demo files. Dashboard tests also boot the published HTML below a repository URL and exercise its fixture adapter and JSON export.

CI installs Python dependencies from `uv.lock` and dashboard test dependencies from `package-lock.json`. The Python matrix covers 3.11, 3.12, 3.13, and 3.14 on Windows and Ubuntu. A separate Ubuntu job runs the JavaScript syntax and behavior checks. Action versions and the uv version are pinned so routine CI runs do not silently switch tooling.

After changing Python dependencies, update `uv.lock` with `uv lock`. After changing dashboard test dependencies, update `package-lock.json` with npm. Commit dependency declarations and their lockfiles together, then run the full checks.

Dependabot checks the Python lockfile, dashboard dependencies, and GitHub Actions every Monday. Minor and patch updates are grouped by ecosystem and can merge automatically after the required checks pass on an up-to-date branch; major upgrades remain separate for review. The `CI gate` check succeeds only when the complete Python matrix and dashboard checks pass, and is the stable check required by branch protection. The automation explicitly refreshes public checks and the demo after a merge.
