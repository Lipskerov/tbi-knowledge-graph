"""
Materialize the vendored frontend libraries into ./lib from the *installed*
pyvis package — no network download. pyvis bundles vis-9.1.2, tom-select and
bindings/utils.js under its templates/ directory; we copy that tree so the
FastAPI app can serve it at /lib (and it lands in the Docker image at build time).

Usage:  python scripts/vendor_lib.py [target_dir]   (default: ./lib)
"""

import shutil
import sys
from pathlib import Path

import pyvis

PKG = Path(pyvis.__file__).parent


def find_lib_src() -> Path:
    # pyvis 0.3.x: pyvis/templates/lib/{vis-9.1.2,tom-select,bindings}
    candidate = PKG / "templates" / "lib"
    if (candidate / "bindings").exists() or any(candidate.glob("vis-*")):
        return candidate
    # Fallback: locate by the vis-network bundle anywhere in the package
    hits = list(PKG.rglob("vis-*/vis-network.min.js"))
    if hits:
        return hits[0].parent.parent
    raise SystemExit(f"Could not find bundled lib/ inside pyvis at {PKG}")


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("lib")
    src = find_lib_src()
    shutil.copytree(src, target, dirs_exist_ok=True)
    files = sum(1 for _ in target.rglob("*") if _.is_file())
    print(f"Vendored frontend libs: {src} -> {target.resolve()} ({files} files)")


if __name__ == "__main__":
    main()
