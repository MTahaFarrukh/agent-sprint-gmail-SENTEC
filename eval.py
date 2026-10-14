"""Compare an agent outbox against an expected-labels file.

Usage:
    python eval.py --outbox outbox_extra.json --expected data/expected_extra.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for key, value in payload.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("email_id", key)
                rows.append(row)
        return rows
    raise ValueError("Expected a JSON list or object of records")


def _id_of(row: dict[str, Any]) -> str:
    return str(row.get("email_id") or row.get("id") or "").strip()


def _norm_refs(refs: Any) -> list[str]:
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    for item in refs:
        code = str(item).strip().upper()
        if code and code not in out:
            out.append(code)
    return out


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = _id_of(row)
        if eid:
            indexed[eid] = row
    return indexed


def evaluate(predicted: list[dict[str, Any]], expected: list[dict[str, Any]]) -> int:
    pred_map = _index(predicted)
    exp_map = _index(expected)
    ids = sorted(exp_map.keys())

    n = len(ids)
    cat_ok = 0
    esc_ok = 0
    ref_ok = 0
    mismatches: list[str] = []

    print(f"Expected {n} emails | Outbox has {len(pred_map)} records")
    print()

    for eid in ids:
        exp = exp_map[eid]
        pred = pred_map.get(eid)
        if pred is None:
            mismatches.append(f"{eid}  MISSING from outbox")
            continue

        exp_cat = str(exp.get("category") or "").strip().lower()
        pred_cat = str(pred.get("category") or "").strip().lower()
        if pred_cat == exp_cat:
            cat_ok += 1
        else:
            mismatches.append(
                f"{eid}  category  expected={exp_cat!r}  got={pred_cat!r}"
            )

        exp_esc = bool(exp.get("escalate"))
        pred_esc = bool(pred.get("escalate"))
        if pred_esc == exp_esc:
            esc_ok += 1
        else:
            mismatches.append(
                f"{eid}  escalate  expected={exp_esc}  got={pred_esc}"
            )

        exp_refs = _norm_refs(exp.get("policy_refs") or exp.get("key_policy_codes"))
        pred_refs = _norm_refs(pred.get("policy_refs"))
        missing = [c for c in exp_refs if c not in pred_refs]
        if not missing:
            ref_ok += 1
        else:
            mismatches.append(
                f"{eid}  policy_refs  expected_key={exp_refs}  got={pred_refs}  "
                f"missing={missing}"
            )

    extra = sorted(set(pred_map) - set(exp_map))
    for eid in extra:
        mismatches.append(f"{eid}  EXTRA in outbox (not in expected file)")

    scored = n if n else 1
    print("Accuracy")
    print(f"  category:    {cat_ok}/{n}  ({100.0 * cat_ok / scored:.1f}%)")
    print(f"  escalate:    {esc_ok}/{n}  ({100.0 * esc_ok / scored:.1f}%)")
    print(f"  policy_refs: {ref_ok}/{n}  ({100.0 * ref_ok / scored:.1f}%)  [expected codes must all appear]")
    print()

    if mismatches:
        print(f"Mismatches ({len(mismatches)})")
        for line in mismatches:
            print(f"  {line}")
        return 1

    print("Mismatches (0)")
    print("  none")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate outbox vs expected labels")
    parser.add_argument(
        "--outbox",
        type=Path,
        default=Path("outbox_extra.json"),
        help="Agent output JSON",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=Path("data") / "expected_extra.json",
        help="Expected labels JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.outbox.is_file():
        print(f"Outbox not found: {args.outbox}", file=sys.stderr)
        return 2
    if not args.expected.is_file():
        print(f"Expected file not found: {args.expected}", file=sys.stderr)
        return 2
    try:
        predicted = _as_list(_load_json(args.outbox))
        expected = _as_list(_load_json(args.expected))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load JSON: {exc}", file=sys.stderr)
        return 2
    return evaluate(predicted, expected)


if __name__ == "__main__":
    raise SystemExit(main())
