# Publish to GitHub

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
