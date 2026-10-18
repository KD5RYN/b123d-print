"""The eval tooling (eval/: runner, agent adapters, corpus) is repo-only: it must not reach the
wheel, the sdist, the Docker image or the runtime dependencies. compare ships."""

import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL_ONLY = re.compile(r"(^|/)(eval|b123d_eval)/|corpus\.toml$|evals/")


@pytest.mark.skipif(not shutil.which("uv"), reason="needs uv")
def test_eval_tooling_not_in_wheel_or_sdist(tmp_path):
    subprocess.run(["uv", "build", "-q", "--out-dir", str(tmp_path)], cwd=ROOT, check=True)
    (whl,), (sdist,) = tmp_path.glob("*.whl"), tmp_path.glob("*.tar.gz")
    with zipfile.ZipFile(whl) as z:
        wheel_names = z.namelist()
        meta = next(z.read(n).decode() for n in wheel_names if n.endswith(".dist-info/METADATA"))
    with tarfile.open(sdist) as t:
        sdist_names = [n.split("/", 1)[1] for n in t.getnames() if "/" in n]
    for names in (wheel_names, sdist_names):
        assert not [n for n in names if EVAL_ONLY.search(n)], "eval tooling leaked into a distribution"
    assert "b123d_print/compare.py" in wheel_names
    assert {"b123d_print/data/styles/functional.toml", "b123d_print/data/design_review.md"} <= set(wheel_names)
    requires = re.findall(r"^Requires-Dist: (\S+)", meta, re.M)
    assert not [r for r in requires if r.startswith("anthropic")], requires


def test_eval_tooling_not_in_docker_image():
    copies = re.findall(r"^COPY\s+(?!--from)(.+)$", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M)
    sources = {s for line in copies for s in line.split()[:-1]}
    assert sources and not sources & {".", "eval", "eval/", "./eval"}, sources
