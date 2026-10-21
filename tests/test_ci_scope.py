"""tools/ci_scope.sh: which pull requests get the quick CI job and which the full run."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def scope(*files: str) -> str:
    r = subprocess.run(["sh", str(ROOT / "tools" / "ci_scope.sh")], input="\n".join(files) + "\n",
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_docs_and_housekeeping_take_the_quick_path():
    assert scope("docs/faq.md", "README.md", "mkdocs.yml", "server.json", "plugin/README.md") == "full=false"
    assert scope(".github/workflows/issue-labels.yml") == "full=false"
    assert scope(".github/workflows/orca-sync.yml", ".github/dependabot.yml", "CONTRIBUTING.md") == "full=false"


def test_code_tests_and_build_workflows_get_the_full_run():
    for f in ("src/b123d_print/cli.py", "tests/test_docs.py", "tools/ci_scope.sh", "pyproject.toml",
              ".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/workflows/docs.yml",
              "src/b123d_print/data/AGENTS.md", "Dockerfile", "deploy/compose.yaml"):
        assert scope(f) == "full=true", f
    assert scope(".github/workflows/issue-labels.yml", "src/b123d_print/cli.py") == "full=true"  # any code: full
    assert scope("") == "full=true"  # nothing listed: run everything
