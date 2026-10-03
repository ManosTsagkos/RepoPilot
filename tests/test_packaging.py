"""Build distributions, then run the installed wheel outside the source checkout."""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
import venv
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def ignore_local_files(directory: str, names: list[str]) -> set[str]:
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "*.egg-info",
    )(directory, names)
    ignored.update(name for name in names if name.startswith(".env") and name != ".env.example")
    return ignored


@pytest.fixture(scope="session")
def distributions(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    workspace = tmp_path_factory.mktemp("distributions")
    source = workspace / "RepoPilot"
    shutil.copytree(ROOT, source, ignore=ignore_local_files)
    # A local configuration file must never become part of a release archive.
    (source / ".env").write_text("PACKAGING_SENTINEL=do-not-ship\n", encoding="utf-8")
    (source / ".env.private").write_text("PACKAGING_SENTINEL=do-not-ship\n", encoding="utf-8")
    output = workspace / "dist"
    # build creates the sdist first and builds the wheel from that source archive.
    run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(output), str(source)],
        workspace,
    )
    wheels = list(output.glob("*.whl"))
    archives = list(output.glob("*.tar.gz"))
    assert len(wheels) == len(archives) == 1
    return wheels[0], archives[0]


def test_source_archive_preserves_setup_and_test_inputs(distributions: tuple[Path, Path]) -> None:
    _, archive = distributions
    with tarfile.open(archive) as source:
        files = {"/".join(Path(member.name).parts[1:]) for member in source if member.isfile()}
    required = {
        ".env.example",
        "MANIFEST.in",
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "package-lock.json",
        "tests/conftest.py",
        "tests/test_packaging.py",
        "tests/frontend/dashboard.test.cjs",
        "tests/frontend/public-demo.test.cjs",
        "scripts/build_demo.py",
        "docs/index.html",
        "docs/demo-data.json",
        "docs/assets/demo-api.js",
        "docs/architecture.md",
        ".github/workflows/ci.yml",
        "src/repopilot/static/app.js",
        "src/repopilot/data/demo.json",
    }
    assert required <= files, f"Missing source files: {required - files}"
    assert ".env" not in files
    assert ".env.private" not in files
    assert not any("node_modules" in Path(name).parts or name.endswith(".pyc") for name in files)


def test_installed_wheel_serves_demo_and_dashboard(
    distributions: tuple[Path, Path], tmp_path: Path
) -> None:
    wheel, _ = distributions
    with ZipFile(wheel) as package:
        names = set(package.namelist())
    assert {
        "repopilot/static/index.html",
        "repopilot/static/app.js",
        "repopilot/static/styles.css",
        "repopilot/static/favicon.svg",
        "repopilot/data/demo.json",
    } <= names

    # ensurepip supplies an offline installer even when the test environment was made by uv.
    installer = tmp_path / "installer"
    venv.EnvBuilder(with_pip=True).create(installer)
    python = installer / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    target = tmp_path / "installed"
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        tmp_path,
    )

    # Use the test environment's runtime dependencies but load RepoPilot from the installed wheel.
    script = textwrap.dedent("""
        import asyncio
        import json
        import sys
        from pathlib import Path

        target = Path(sys.argv[1]).resolve()
        sys.path.insert(0, str(target))
        import httpx
        import repopilot
        from repopilot.config import Settings
        from repopilot.main import create_app

        assert Path(repopilot.__file__).resolve().is_relative_to(target)

        async def check():
            app = create_app(Settings(openai_api_key=None, github_token=None, _env_file=None))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://localhost"
                ) as client:
                    health = await client.get("/api/health")
                    assert health.status_code == 200
                    assert health.json()["status"] == "ok"
                    assets = ("/", "/static/app.js", "/static/styles.css", "/static/favicon.svg")
                    for path in assets:
                        response = await client.get(path)
                        assert response.status_code == 200, path
                        assert response.content, path
                    response = await client.get("/api/issues?mode=demo")
                    assert response.status_code == 200
                    issues = response.json()
                    assert issues["issues"]
                    result = await client.post("/api/analyze", json={
                        "repository": issues["repository"],
                        "issue_number": issues["issues"][0]["number"],
                        "mode": "demo",
                    })
                    assert result.status_code == 200
                    assert result.json()["provider"] == "demo"
                    assert result.json()["analysis"]["summary"]
            print(json.dumps({"installed_from": str(target), "demo": "ok"}))

        asyncio.run(check())
    """)
    output = run([sys.executable, "-I", "-c", script, str(target)], tmp_path)
    assert json.loads(output)["demo"] == "ok"
