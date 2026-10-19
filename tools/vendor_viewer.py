"""Rebuild the vendored three.js bundle the 3D viewer loads (src/b123d_print/data/viewer/).

    uv run python tools/vendor_viewer.py          # needs network (npm registry) and node (npx)

What it does, so the shipped file can be checked against its source:
1. downloads three@THREE_VERSION from the npm registry and checks the tarball's integrity hash
   (THREE_INTEGRITY, the registry's sha512) before unpacking anything;
2. bundles exactly the names in EXPORTS (the ones viewer.js uses, see tests/test_viewer.py) with
   esbuild@ESBUILD_VERSION into one minified IIFE that defines the global B123D_THREE;
3. puts three.js's whole MIT license (the LICENSE file of that tarball) at the top of the
   bundle, so every copy of it carries the notice: the served file and every offline view
   HTML (b123d-print view), which embeds the bundle;
4. writes three-LICENSE.txt next to it and vendor.json (versions, hashes, size).

Only three.js code goes into the bundle (core, GLTFLoader, OrbitControls and the utils
GLTFLoader imports). GLTFLoader's optional Draco / meshopt / KTX2 decoders are not imported and
not shipped. esbuild only runs here; it is not shipped.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

THREE_VERSION = "0.186.1"
THREE_INTEGRITY = "sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA=="
ESBUILD_VERSION = "0.28.1"
EXPORTS = {
    "three": ["Box3", "Box3Helper", "Color", "DirectionalLight", "DoubleSide", "EdgesGeometry", "GridHelper", "Group",
              "HemisphereLight", "LineBasicMaterial", "LineSegments", "LoadingManager", "MathUtils", "Mesh",
              "MeshBasicMaterial", "PerspectiveCamera", "Plane", "PlaneGeometry", "REVISION", "Scene", "Sphere",
              "Vector3", "WebGLRenderer"],
    "three/examples/jsm/loaders/GLTFLoader.js": ["GLTFLoader"],
    "three/examples/jsm/controls/OrbitControls.js": ["OrbitControls"],
}
OUT = Path(__file__).resolve().parents[1] / "src" / "b123d_print" / "data" / "viewer"
BUNDLE = "three.bundle.min.js"


def fetch(version: str, integrity: str) -> bytes:
    url = f"https://registry.npmjs.org/three/-/three-{version}.tgz"
    data = urllib.request.urlopen(url, timeout=120).read()
    algo, _, want = integrity.partition("-")
    got = base64.b64encode(hashlib.new(algo, data).digest()).decode()
    if got != want:
        sys.exit(f"integrity mismatch for {url}: got {algo}-{got}, expected {integrity}")
    return data


def main() -> int:
    if not shutil.which("npx"):
        sys.exit("needs node (npx) on PATH")
    tgz = fetch(THREE_VERSION, THREE_INTEGRITY)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        mods = work / "node_modules"
        with tarfile.open(fileobj=io.BytesIO(tgz)) as t:
            t.extractall(mods, filter="data")
        (mods / "package").rename(mods / "three")
        license_text = (mods / "three" / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in license_text, "three.js is not MIT any more: stop and review the license"
        entry = work / "entry.js"
        entry.write_text("".join(f"export {{ {', '.join(names)} }} from {json.dumps(mod)};\n"
                                 for mod, names in EXPORTS.items()), encoding="utf-8")
        banner = ("/*! three.js r" + THREE_VERSION.split(".")[1] + f" (npm three@{THREE_VERSION}), bundled for "
                  "b123d-print's 3D viewer: core, GLTFLoader, OrbitControls.\n"
                  + license_text.strip().replace("*/", "* /") + "\n*/")
        out = work / BUNDLE
        subprocess.run(["npx", "--yes", f"esbuild@{ESBUILD_VERSION}", str(entry), "--bundle", "--minify",
                        "--format=iife", "--global-name=B123D_THREE", "--target=es2020", "--legal-comments=inline",
                        f"--banner:js={banner}", f"--outfile={out}"], cwd=work, check=True)
        code = out.read_text(encoding="utf-8")
        low = code.lower()
        # the offline HTML inlines the bundle in a <script>: nothing in it may end or escape that element
        assert "</script" not in low and "<!--" not in low and "<script" not in low, "bundle needs escaping for inline use"
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / BUNDLE).write_text(code, encoding="utf-8", newline="\n")
        (OUT / "three-LICENSE.txt").write_text(license_text, encoding="utf-8", newline="\n")
    meta = {
        "library": "three.js", "package": f"three@{THREE_VERSION}", "license": "MIT",
        "source": f"https://registry.npmjs.org/three/-/three-{THREE_VERSION}.tgz", "integrity": THREE_INTEGRITY,
        "bundler": f"esbuild@{ESBUILD_VERSION}", "exports": EXPORTS,
        "file": BUNDLE, "sha256": hashlib.sha256((OUT / BUNDLE).read_bytes()).hexdigest(),
        "bytes": (OUT / BUNDLE).stat().st_size,
    }
    (OUT / "vendor.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{BUNDLE}: {meta['bytes']:,} bytes, sha256 {meta['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
