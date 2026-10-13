"""Smoke-test the LLM wrapper with a tiny JSON prompt.

Usage (from any directory, venv active):
    python scripts/test_llm.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import GEMINI_API_KEY, LLM_MODEL, LLM_PROVIDER, ROOT_DIR
from src.llm import generate_json


def main() -> None:
    print(f"ROOT_DIR={ROOT_DIR}")
    print(f"LLM_PROVIDER={LLM_PROVIDER}")
    print(f"LLM_MODEL={LLM_MODEL}")
    print(f"GEMINI_API_KEY set={bool(GEMINI_API_KEY)} len={len(GEMINI_API_KEY)}")
    print('Calling generate_json with prompt: Return JSON {"ok": true}')
    try:
        result = generate_json(
            system_prompt="You return only valid JSON objects. No markdown.",
            user_prompt='Return JSON {"ok": true}',
        )
        print("OK parsed:", result)
    except Exception as exc:  # noqa: BLE001 — show full failure for diagnosis
        print(f"FAILED {type(exc).__name__}: {exc}")
        print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
