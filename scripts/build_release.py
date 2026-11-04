"""Build a distributable wheel with the web UI bundled: `python scripts/build_release.py`.

Steps: build the frontend, copy it into backend/missync/_static, then build sdist + wheel into ./dist.
Requires Node/npm and `pip install build`.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "backend" / "missync" / "_static"
npm = "npm.cmd" if sys.platform == "win32" else "npm"


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> None:
    run([npm, "ci"], ROOT / "frontend")
    run([npm, "run", "build"], ROOT / "frontend")
    shutil.rmtree(STATIC, ignore_errors=True)
    shutil.copytree(ROOT / "frontend" / "dist", STATIC)
    run([sys.executable, "-m", "build", "--outdir", str(ROOT / "dist"), str(ROOT / "backend")], ROOT)
    print(f"\nBuilt: {sorted(p.name for p in (ROOT / 'dist').glob('*'))}")


if __name__ == "__main__":
    main()
