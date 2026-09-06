"""Check the documentation's claims about itself against the repository.

ISSUES.md #30 counted eighteen instances of one failure: a document states a
count, a command list, or a guarantee, and the code moves without it. Five
were found by accident, thirteen by looking, and its own conclusion is that
counting them again is not the fix - "a durable document that also carries
perishable status will always drift, no matter how carefully any one edit is
checked. The fix has to be structural or the tenth instance is only a matter
of time."

This is that structure, for the claims a machine can check. It is not a
substitute for reading: it cannot tell whether a sentence is TRUE, only
whether a number that appears in two places still agrees with the thing it
counts.

Deliberately narrow. Every assertion here is about a count or a list that
exists in two places at once, which is the shape every instance in #30 had.
Nothing here checks prose.

No PDFs, no API key, no imports from aleph - it reads files. Runs in CI.
"""
import re
import sys
from pathlib import Path

README = Path("README.md")
CLAUDE = Path("CLAUDE.md")
WORKFLOW = Path(".github/workflows/pipeline-tests.yml")
GATES = Path("src/aleph/extraction/gates.py")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(f"{label} {detail}")


def command_block(text: str) -> list[str]:
    """The fenced block listing the commands that verify the system."""
    for match in re.finditer(r"```\r?\n(.*?)```", text, re.S):
        body = match.group(1)
        if "run_valuation.py UBER_FY2024" in body:
            return [line.rstrip() for line in body.strip().splitlines()]
    return []


def test_command_lists_are_identical():
    """README says its list is "verbatim from CLAUDE.md". #30's instance 5
    was that sentence being false - the README faithfully reproduced
    CLAUDE.md's staleness rather than inventing its own."""
    readme, claude = command_block(README.read_text(encoding="utf-8")), \
        command_block(CLAUDE.read_text(encoding="utf-8"))
    check("command block found in README", bool(readme))
    check("command block found in CLAUDE.md", bool(claude))
    check("the two command lists are identical", readme == claude,
          f"README={len(readme)} CLAUDE={len(claude)}")
    return readme


def test_every_documented_script_exists(commands: list[str]):
    """A documented command that cannot run was #30's instance 4."""
    for line in commands:
        match = re.search(r"(scripts\\[\w.]+\.py)", line)
        if not match:
            continue
        path = Path(match.group(1).replace("\\", "/"))
        check(f"{path} exists", path.exists())


WORDS = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
    7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven",
    12: "Twelve", 13: "Thirteen", 14: "Fourteen", 15: "Fifteen",
}


def word(n: int) -> str | None:
    """The English word these documents spell counts with, or None.

    None is a real answer, not a failure: past fifteen the documents should
    switch to digits, and a checker that silently accepted a missing word
    would stop checking exactly when the list grew.
    """
    return WORDS.get(n)


def test_prose_counts_match_the_command_list(commands: list[str]):
    """"Ten commands prove the pipeline works" must count the same list."""
    readme = README.read_text(encoding="utf-8")
    expected = word(len(commands))
    check(f"README says '{expected} commands' for {len(commands)} commands",
          expected is not None and f"{expected} commands" in readme)


def test_ci_runs_only_scripts_that_exist_and_are_documented(commands: list[str]):
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ci_scripts = re.findall(r"run: python (scripts/[\w.]+\.py)", workflow)
    check("CI runs at least one test script", bool(ci_scripts))
    for script in ci_scripts:
        check(f"CI script {script} exists", Path(script).exists())
        name = script.split("/")[-1]
        check(f"CI script {name} is in the documented list",
              any(name in line for line in commands))
    return ci_scripts


def test_ci_coverage_claims_match_what_it_runs(commands, ci_scripts):
    """The workflow states what it does NOT cover. That statement is itself a
    count, so it drifts like any other."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    covered, total = len(ci_scripts), len(commands)
    check(f"CI echo claims '{covered} of the {total}'",
          f"{covered} of the {total} documented" in workflow)

    uncovered, total_word = word(total - covered), word(total)
    expected = (f"{uncovered} of the {total_word.lower()} commands"
                if uncovered and total_word else None)
    check(f"CI comment claims '{expected}'",
          expected is not None and expected in workflow,
          f"{total} documented - {covered} covered = {total - covered} uncovered")


def test_gate_count_is_not_stale():
    """#30's instance 3: CLAUDE.md said five correctness gates after a sixth
    was added. The count lives in two prose files and one module."""
    source = GATES.read_text(encoding="utf-8")
    correctness = [n for n in re.findall(r"^def (check_\w+)", source, re.M)
                   if n != "check_coverage"]
    has_coverage = "def check_coverage" in source
    readme = README.read_text(encoding="utf-8")
    claude = CLAUDE.read_text(encoding="utf-8")

    check(f"gates.py defines {len(correctness)} correctness gates + coverage",
          len(correctness) == 6 and has_coverage,
          f"found {correctness}, coverage={has_coverage}")
    check("README says 'Six gates'", "Six gates" in readme)
    check("README says a seventh, separate gate", "A seventh, separate gate" in readme)
    check("CLAUDE.md says '6 correctness'", "6 correctness" in claude)
    check("CLAUDE.md principle 8 says 'Six gates'", "Six gates" in claude)


def test_adr_count_matches_the_directory():
    adrs = sorted(Path("docs/adr").glob("*.md"))
    claude = CLAUDE.read_text(encoding="utf-8")
    check(f"{len(adrs)} ADR files on disk", len(adrs) > 0)
    # CLAUDE.md must not name a count that has moved past it.
    stale = re.search(r"(\w+) ADRs", claude)
    if stale:
        check(f"CLAUDE.md's ADR count '{stale.group(1)}' is not a stale number",
              False, "CLAUDE.md should point at docs/adr/, not count it")


if __name__ == "__main__":
    print("Command lists:")
    commands = test_command_lists_are_identical()
    test_every_documented_script_exists(commands)
    test_prose_counts_match_the_command_list(commands)

    print("CI:")
    ci_scripts = test_ci_runs_only_scripts_that_exist_and_are_documented(commands)
    test_ci_coverage_claims_match_what_it_runs(commands, ci_scripts)

    print("Counts stated in two places:")
    test_gate_count_is_not_stale()
    test_adr_count_matches_the_directory()

    if failures:
        print(f"\n{len(failures)} documentation claim(s) no longer match the code:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print("\nAll documentation claims match the code.")
