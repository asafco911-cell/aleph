"""CI entry point. Exit code 0 = pass, 1 = block the merge.
Ordered cheapest-and-surest first: structural tests, then security, then evaluation."""
import sys
import json
from pathlib import Path

from security import sanitize_document, scan_for_injection

REPO_ROOT = Path(__file__).resolve().parents[2]

# Quality metrics are probabilistic - they need tolerance, not equality.
# Derive these from measured variance (run the suite 5x, use ~2 sigma), not from feel.
THRESHOLDS = {
    "faithfulness": {"min": 0.80, "tolerance": 0.02},
    "retrieval_hit": {"min": 0.75, "tolerance": 0.03},
    "correctness": {"min": 0.70, "tolerance": 0.03},
}

failures = []
warnings = []


def check_secrets_not_committed():
    """A leaked API key is permanent - git history keeps it forever.
    Must not flag the scanner's own pattern definitions (a self-detecting scanner
    trains people to ignore it, which is worse than having no scanner)."""
    import re

    gitignore = REPO_ROOT / ".gitignore"
    if not gitignore.exists() or ".env" not in gitignore.read_text():
        failures.append("SECRET: .env is not listed in .gitignore")

    # Match a key-shaped string with real payload length, not the prefix alone
    key_shapes = [
        re.compile(r"sk-ant-[A-Za-z0-9_-]{30,}"),
        re.compile(r"ghp_[A-Za-z0-9]{36}"),
    ]
    # Files whose job is to define these patterns are excluded by design
    skip_files = {"security.py", "run_ci_checks.py"}

    for path in REPO_ROOT.rglob("*.py"):
        if "venv" in str(path) or path.name in skip_files:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for shape in key_shapes:
            if shape.search(text):
                failures.append(
                    f"SECRET: key-shaped string in {path.relative_to(REPO_ROOT)}")
                break
    print("  [ok] secret scan")


def check_deterministic_tests():
    """Structural tests are binary - any failure blocks immediately."""
    import subprocess
    suites = [
        ("DCF engine", REPO_ROOT / "experiments/ch09_dcf/test_engine.py"),
        ("Forensics", REPO_ROOT / "experiments/ch10_forensics/test_forensics.py"),
    ]
    for name, path in suites:
        if not path.exists():
            warnings.append(f"{name} test suite not found at {path}")
            continue
        result = subprocess.run([sys.executable, path.name], cwd=path.parent,
                                capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(f"TEST: {name} failed\n{result.stdout[-400:]}")
        else:
            print(f"  [ok] {name} tests")


def check_golden_dataset_integrity():
    """The golden dataset is the answer key - if it's malformed, every score is invalid."""
    path = REPO_ROOT / "experiments/ch05_evaluation/golden_dataset.json"
    if not path.exists():
        failures.append("EVAL: golden_dataset.json not found")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        failures.append(f"EVAL: golden_dataset.json is not valid JSON - {e}")
        return

    required = {"question", "ground_truth", "source_pages", "question_type"}
    for i, item in enumerate(data):
        missing = required - set(item)
        if missing:
            failures.append(f"EVAL: question {i} missing fields {missing}")
    types = {}
    for item in data:
        types[item.get("question_type")] = types.get(item.get("question_type"), 0) + 1
    for qtype, count in types.items():
        if count < 3:
            warnings.append(f"EVAL: only {count} '{qtype}' questions - too few to conclude from")
    print(f"  [ok] golden dataset: {len(data)} questions, types={types}")


if __name__ == "__main__":
    print("=" * 70)
    print("CI FAST GATE (free, deterministic)")
    print("=" * 70)
    check_secrets_not_committed()
    check_deterministic_tests()
    check_golden_dataset_integrity()

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    for w in warnings:
        print(f"  WARN  {w}")
    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(f"\n  BLOCKED: {len(failures)} failure(s)")
        sys.exit(1)                       # non-zero exit blocks the merge
    print(f"\n  PASSED ({len(warnings)} warning(s))")
    sys.exit(0)