# Publishing and the public demo

The repository is available at [github.com/ManosTsagkos/RepoPilot](https://github.com/ManosTsagkos/RepoPilot). Its [interactive demo](https://manostsagkos.github.io/RepoPilot/) runs on GitHub Pages.

## Updating the demo

Run `python scripts/build_demo.py` from the repository root after changing the dashboard or sample data. Commit the generated files in `docs/` together with the source changes. CI verifies that they match with `python scripts/build_demo.py --check`.

GitHub Pages publishes from **main /docs**. The `.nojekyll` file keeps the generated HTML, JavaScript, CSS, and JSON unchanged. The demo loads only its public sample data; it does not contain credentials or call GitHub/OpenAI APIs. Screenshots and the downloadable sample JSON are also in `docs/`.

For a fork, update the demo links in the README, set the repository's About website to its Pages URL, and enable Pages from the main branch's `/docs` folder in repository settings.

## Publishing another checkout

Run these commands from the RepoPilot directory. They assume that you have Git installed and that `ManosTsagkos` is the GitHub account where you want to publish the project.

## Check the files

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
npm ci
npm run check
npm test
```

The npm commands need a current Node.js 24 release. They run dashboard development checks and do not create a frontend build. For a reproducible Python environment, use `uv sync --locked --extra dev` before the checks and prefix Python commands with `uv run --locked --extra dev`.

If this is a fresh directory, initialize it:

```sh
git init -b main
git add .
git status
git diff --cached
```

Review the staged files. `.env`, `.venv`, caches, and API keys should not be present. If this directory is already a Git repository, inspect its branch and remote instead of initializing it again.

```sh
git commit -m "Add RepoPilot issue assistant"
```

## Create the repository

With the GitHub CLI installed and authenticated to your account:

```sh
gh auth status
gh repo create ManosTsagkos/RepoPilot --public --source=. --remote=origin --push
```

Alternatively, create an empty repository named `RepoPilot` on GitHub. Leave its README, license, and `.gitignore` uninitialized, since those files are already included here. Then run:

```sh
git remote add origin https://github.com/ManosTsagkos/RepoPilot.git
git push -u origin main
```

If an `origin` remote already exists, inspect `git remote -v` before changing it. Do not overwrite a remote pointing to another project.

## Repository details

Suggested description:

> AI GitHub issue assistant built with Python, FastAPI, GitHub REST API, and structured LLM output.

Suggested topics: `python`, `fastapi`, `github-api`, `llm`, `openai`, `issue-triage`.

After publishing, check the Actions tab for the test and lint result. Add the repository to your GitHub profile's pinned projects if you want it visible in your portfolio.

For screenshots or a short demo recording, use offline mode or a public issue. Do not include API keys or private issue contents in the recording.
