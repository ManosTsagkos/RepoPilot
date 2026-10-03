"""Build the public GitHub Pages demo from the app's dashboard and validated samples."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from repopilot import __version__
from repopilot.github import normalize_issue
from repopilot.models import Analysis, AnalysisResult
from repopilot.service import DEMO_REPOSITORY

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "repopilot" / "static"
REPOSITORY_URL = "https://github.com/ManosTsagkos/RepoPilot"


def build(output: Path) -> None:
    assets = output / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "styles.css", "favicon.svg", "demo-api.js"):
        shutil.copyfile(STATIC / name, assets / name)
    html = (STATIC / "index.html").read_text("utf-8")
    html = html.replace('href="/static/', 'href="./assets/')
    html = html.replace('src="/static/', 'src="./assets/')
    html = html.replace('href="/"', 'href="./"')
    html = html.replace('href="/docs"', f'href="{REPOSITORY_URL}#api"')
    html = html.replace("API reference", "Project source")
    html = html.replace("Suggestions only", "Interactive demo")
    html = html.replace(
        '<script defer src="./assets/app.js"></script>',
        '<script defer src="./assets/demo-api.js"></script>\n'
        '    <script defer src="./assets/app.js"></script>',
    )
    html = html.replace(
        'id="live-mode"',
        'id="live-mode" disabled title="Run locally to connect a real repository"',
    )
    (output / "index.html").write_text(html, encoding="utf-8", newline="\n")
    raw = json.loads((ROOT / "src/repopilot/data/demo.json").read_text("utf-8"))
    samples = [
        AnalysisResult(
            repository=DEMO_REPOSITORY,
            mode="demo",
            issue=normalize_issue(item["issue"], DEMO_REPOSITORY),
            analysis=Analysis.model_validate(item["analysis"]),
            provider="demo",
            model=None,
        ).model_dump()
        for item in raw
    ]
    data = {
        "config": {
            "github_configured": False,
            "llm_configured": False,
            "model": None,
            "demo_repository": DEMO_REPOSITORY,
            "version": __version__,
        },
        "samples": samples,
    }
    for name, value in (("demo-data.json", data), ("sample-analysis.json", samples[0])):
        (output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    (output / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    parser.add_argument("--check", action="store_true", help="Check committed demo files for drift")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory() as folder:
            generated = Path(folder)
            build(generated)
            for path in generated.rglob("*"):
                if path.is_file():
                    committed = args.output / path.relative_to(generated)
                    if not committed.is_file() or path.read_bytes() != committed.read_bytes():
                        parser.exit(1, f"Rebuild demo: {committed}\n")
    else:
        build(args.output)


if __name__ == "__main__":
    main()
