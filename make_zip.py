"""Build TeenHaseen_AgentSprint.zip for submission, then smoke-test it.

Usage:
    python make_zip.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIP_NAME = "TeenHaseen_AgentSprint.zip"

# Exact files / trees to include (relative to ROOT).
INCLUDE_FILES = [
    "agent.py",
    "policy.py",
    "llm.py",
    "validator.py",
    "dashboard.py",
    "eval.py",
    "requirements.txt",
    "README.md",
    ".env.example",
    "outbox.json",
    "data/policy.md",
    "data/expected_extra.json",
]
INCLUDE_DIRS = [
    "data/inbox",
    "data/inbox_extra",
    "logs",
]
# Only these log files (if present).
LOG_FILES = ("agent.log", "trace.jsonl")

EXCLUDE_NAME_PARTS = {
    ".env",
    "venv",
    ".git",
    "src",
    "scripts",
    "docs",
    "credentials.json",
    "token.json",
    "__pycache__",
}


def _load_api_key() -> str:
    key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    if key:
        return key
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
            key = value.strip().strip('"').strip("'")
            if key:
                return key
    return ""


def _should_skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_NAME_PARTS:
        return True
    name = rel.name
    if name == ".env":
        return True
    if name.startswith("outbox_") and name.endswith(".json"):
        return True
    if name.endswith(".pyc") or name == "__pycache__":
        return True
    return False


def _collect_paths() -> list[Path]:
    paths: list[Path] = []
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.is_file():
            paths.append(p)
        else:
            print(f"[warn] missing file (skipped): {rel}")

    for rel_dir in INCLUDE_DIRS:
        d = ROOT / rel_dir
        if not d.is_dir():
            print(f"[warn] missing dir (skipped): {rel_dir}")
            continue
        if rel_dir == "logs":
            for name in LOG_FILES:
                p = d / name
                if p.is_file():
                    paths.append(p)
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if _should_skip(rel):
                continue
            paths.append(p)
    # De-dupe while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def _ensure_env_example() -> None:
    """Guarantee .env.example has an empty GEMINI_API_KEY= line."""
    path = ROOT / ".env.example"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "GEMINI_API_KEY=" not in text:
        text = "GEMINI_API_KEY=\n" + text
        path.write_text(text, encoding="utf-8")
        return
    # Normalize: ensure the assignment is empty (no value after =).
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("GEMINI_API_KEY="):
            lines.append("GEMINI_API_KEY=")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_zip(zip_path: Path) -> list[str]:
    """Write the zip; return list of archived relative paths."""
    _ensure_env_example()
    files = _collect_paths()
    if zip_path.exists():
        zip_path.unlink()

    archived: list[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            if _should_skip(Path(rel)):
                continue
            zf.write(path, rel)
            archived.append(rel)
    return archived


def smoke_test(zip_path: Path, api_key: str) -> int:
    """Extract zip to a temp folder and run python agent.py --limit 2."""
    if not api_key:
        print("[problem] No GEMINI_API_KEY available for smoke test.")
        return 1

    with tempfile.TemporaryDirectory(prefix="teenhaseen_zip_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_path)

        # Package must not rely on src/
        if (tmp_path / "src").exists():
            print("[problem] zip unexpectedly contains src/")
            return 1

        env = os.environ.copy()
        env["GEMINI_API_KEY"] = api_key
        # Force discovery path unless the judge pins a model.
        env.pop("LLM_MODEL", None)
        # Keep GEMINI_MODEL if the user set it; otherwise discovery runs.
        print(f"\n--- smoke test in {tmp_path} ---")
        print("Running: python agent.py --limit 2")
        proc = subprocess.run(
            [sys.executable, "agent.py", "--limit", "2"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        print(f"smoke_test exit_code={proc.returncode}")
        outbox = tmp_path / "outbox.json"
        if outbox.is_file():
            print(f"outbox.json bytes={outbox.stat().st_size}")
        return proc.returncode


def main() -> int:
    zip_path = ROOT / ZIP_NAME
    print(f"Building {zip_path.name} from {ROOT}")
    archived = build_zip(zip_path)
    print(f"Wrote {len(archived)} entries -> {zip_path}")
    for rel in archived:
        print(f"  + {rel}")

    # Sanity: forbidden paths must not appear
    bad = [
        r
        for r in archived
        if r.startswith("src/")
        or r.startswith("scripts/")
        or r.startswith("docs/")
        or r == ".env"
        or "/__pycache__/" in r
        or Path(r).name.startswith("outbox_")
    ]
    if bad:
        print("[problem] zip contains excluded paths:")
        for r in bad:
            print(f"  - {r}")
        return 1

    api_key = _load_api_key()
    return smoke_test(zip_path, api_key)


if __name__ == "__main__":
    raise SystemExit(main())
