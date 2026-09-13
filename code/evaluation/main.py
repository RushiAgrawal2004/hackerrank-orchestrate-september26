"""Scorer entry point for the evaluation/ folder.

    python3 code/evaluation/main.py            # from the repo root (repository layout)
    python3 evaluation/main.py                 # from the unzipped code.zip root (code/ next to evaluation/)
    python3 code/evaluation/main.py --quiet    # summary only; any evaluate.py flag is passed through

Scores the planner against dataset/sample_requests.csv with the fitted flags in code/best_config.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = [HERE.parent, HERE.parent / "code"]
CODE_DIR = next((c for c in CANDIDATES if (c / "engine.py").exists()), None)
if CODE_DIR is None:
    sys.exit(f"could not find engine.py in {[str(c) for c in CANDIDATES]}")
sys.path.insert(0, str(CODE_DIR))

import evaluate  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--config" not in args:
        args = ["--config", str(CODE_DIR / "best_config.json"), *args]
    sys.argv = [str(CODE_DIR / "evaluate.py"), *args]
    evaluate.main()
