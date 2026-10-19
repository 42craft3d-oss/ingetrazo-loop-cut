"""Small offline pre-release check for the standalone Loop Cut package."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED = (
    "loop_cut.py",
    "LICENSE",
    "README.md",
    "README.en.md",
    "README.pt-BR.md",
    "RELEASE_NOTES.md",
    "media/loop-selection-v1.1.0.png",
)


def main() -> None:
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("Missing required files: " + ", ".join(missing))

    source = (ROOT / "loop_cut.py").read_text(encoding="utf-8")
    ast.parse(source, filename="loop_cut.py")
    for token in ("_quad_plan_from_face", "_ring_from_edge",
                  "Qt.AltModifier", "Qt.ShiftModifier"):
        if token not in source:
            raise SystemExit(f"Required behavior is missing: {token}")

    print("Loop Cut v1.1.0 package check passed.")
    for name in REQUIRED:
        path = ROOT / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(f"{name}: {digest}")


if __name__ == "__main__":
    main()
