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
import subprocess
import sys
from pathlib import Path

README = Path("README.md")
CLAUDE = Path("CLAUDE.md")
WORKFLOW = Path(".github/workflows/pipeline-tests.yml")
GATES = Path("src/aleph/extraction/gates.py")
OPERATING_MODEL = Path("src/aleph/valuation/operating_model.py")
PYPROJECT = Path("pyproject.toml")
CONFTEST = Path("tests/conftest.py")

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


def test_no_workflow_needs_a_file_the_repository_does_not_ship():
    """A workflow that reads an undistributed file can only ever fail.

    eval-gate.yml ran `experiments/ch05_evaluation/02_ab_test.py` on every
    pull request; that script opens data/uber_10k.pdf at module level, and
    the filings are deliberately not distributed (docs/adr/0006). It was
    guaranteed to fail on the first PR, for a reason unrelated to the change
    under review. Deleted in docs/adr/0008.

    This walks every script a workflow runs and fails if it references a
    path that git does not track - which is what "not distributed" means to
    a CI runner.
    """
    tracked = set(subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True
    ).stdout.splitlines())

    for workflow in sorted(Path(".github/workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for script in re.findall(r"run: python (\S+\.py)", text):
            check(f"{workflow.name} runs {script}, which exists",
                  Path(script).exists())
            if not Path(script).exists():
                continue
            source = Path(script).read_text(encoding="utf-8")
            for ref in re.findall(r'["\']((?:data|experiments)/[\w./-]+)["\']', source):
                # Only a path that EXISTS locally but is not tracked is
                # the bug: it works on the author's machine and is absent
                # on a runner. A path that exists nowhere is a fixture
                # string - test_manifest.py deliberately passes
                # "data/does-not-exist" to prove a missing manifest is
                # not an error.
                if not Path(ref).exists() or ref in tracked:
                    continue
                check(f"{script} reads {ref}, which the repository ships",
                      False,
                      "exists locally, untracked: a CI runner lacks it")


def test_no_inert_workflow_sits_outside_the_workflows_directory():
    """`.github/fast-gate.yml` declared `on: push` and a job, and sat one
    directory above `.github/workflows/` - the only place GitHub Actions reads
    workflow files from. It was inert, and nothing in the file said so.

    The check above globs `.github/workflows/*.yml`, so it never saw this one:
    a file that is not a workflow cannot fail a workflow check. This is the
    complement - anything under `.github/` that LOOKS like a workflow and is
    not where workflows live.
    """
    strays = sorted(Path(".github").glob("*.yml")) + \
        sorted(Path(".github").glob("*.yaml"))
    check("no stray workflow-shaped file directly under .github/",
          not [p for p in strays
               if "jobs:" in p.read_text(encoding="utf-8")],
          f"{[str(p) for p in strays]} - GitHub Actions reads only "
          ".github/workflows/, so a job declared here never runs")


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


def test_operating_model_docstring_matches_the_bridge():
    """P10 fixed a real SBC double-count in the P9 driver bridge: fcff_t no
    longer subtracts sbc_t - SBC is a GAAP opex already inside operating
    income, so it is reported only. The module docstring's own formula
    listing is the SECOND place that claim lives; closeout hardening found
    it had not been updated with the code - the exact #30 shape, one prose
    block and one arithmetic line drifting apart."""
    source = OPERATING_MODEL.read_text(encoding="utf-8")
    # only the structured formula lines - "THE BRIDGE (Phase 11)" through the
    # closing "= fcff_t" - NOT the prose paragraph after it, which legitimately
    # narrates the old, wrong formula as history ("an earlier version ...
    # subtracted a separate `- sbc_t` term"). Checking prose would false-fail
    # on its own explanation of the bug it is documenting.
    doc_match = re.search(r"THE BRIDGE \(Phase 11\).*?= fcff_t", source, re.S)
    code_match = re.search(r"^        fcff_t = .*$", source, re.M)
    check("operating_model.py docstring's bridge formula is present",
          doc_match is not None)
    check("operating_model.py bridge code line is present",
          code_match is not None)
    if doc_match and code_match:
        check("docstring's bridge formula does not subtract sbc_t",
              "- sbc_t" not in doc_match.group(0),
              "docstring still lists '- sbc_t' as a subtracted bridge term - "
              "stale since the P10 SBC double-count fix")
        check("the actual bridge code does not subtract sbc_t (P10 fix holds)",
              "- sbc_t" not in code_match.group(0), code_match.group(0).strip())


def test_adr_count_matches_the_directory():
    adrs = sorted(Path("docs/adr").glob("*.md"))
    claude = CLAUDE.read_text(encoding="utf-8")
    check(f"{len(adrs)} ADR files on disk", len(adrs) > 0)
    # CLAUDE.md must not name a count that has moved past it.
    stale = re.search(r"(\w+) ADRs", claude)
    if stale:
        check(f"CLAUDE.md's ADR count '{stale.group(1)}' is not a stale number",
              False, "CLAUDE.md should point at docs/adr/, not count it")

    # README's layout block DOES name the count - "docs/adr/  eight decisions
    # that had a real rejected alternative". It said "six" while eight files
    # sat on disk: two ADRs were added and the sentence that counts them was
    # not. #30's shape exactly, and the reason this check exists.
    readme = README.read_text(encoding="utf-8")
    stated = re.search(r"docs/adr/\s+(\w+) decisions", readme)
    check("README's layout block states an ADR count", stated is not None,
          "expected a line like 'docs/adr/   eight decisions'")
    if stated:
        expected = word(len(adrs))
        check(f"README says '{expected} decisions' for {len(adrs)} ADR files",
              expected is not None
              and stated.group(1).lower() == expected.lower(),
              f"README says '{stated.group(1)}', docs/adr/ holds {len(adrs)}")


def uber_facts_section() -> tuple[str, list[str]]:
    """CLAUDE.md's "Six 10-K facts" heading word, and the bullets under it."""
    claude = CLAUDE.read_text(encoding="utf-8")
    match = re.search(r"^## (\w+) \"10-K facts\".*?$(.*?)(?=^## )",
                      claude, re.S | re.M)
    if not match:
        return "", []
    bullets = re.findall(r"^- ", match.group(2), re.M)
    return match.group(1), bullets


def test_uber_facts_count_agrees_everywhere():
    """The list of rules that turned out to be Uber-specific lives in two
    documents and is counted in three sentences. README said "Five rules"
    while CLAUDE.md's heading said "Six" over six bullets - the sixth (two
    tax-rate tables after ASU 2023-09) had been added to the list without the
    README sentence that counts it.

    The bullets are the thing; both headings and both sentences are counts OF
    them, so the bullets are what this counts.
    """
    heading_word, bullets = uber_facts_section()
    readme = README.read_text(encoding="utf-8")

    check("CLAUDE.md's '10-K facts' section found", bool(bullets),
          f"heading word={heading_word!r}, bullets={len(bullets)}")
    if not bullets:
        return

    expected = word(len(bullets))
    check(f"CLAUDE.md heading says '{expected}' for {len(bullets)} bullets",
          expected is not None and heading_word.lower() == expected.lower(),
          f"heading says '{heading_word}'")
    check(f"README says '{expected} rules'",
          expected is not None
          and f"{expected} rules that looked like general" in readme,
          f"{len(bullets)} bullets in CLAUDE.md")
    check(f"README's closing sentence says 'those {str(expected).lower()} failures'",
          expected is not None
          and f"those {expected.lower()} failures" in readme)


ANCHOR_LABEL = "Latest-period basis"
CLI = Path("scripts/run_valuation.py")


def test_the_anchor_is_quoted_under_the_label_the_cli_prints():
    """`data/README.md` wrote the 77.08 anchor as `Value per share: 77.08`.
    The CLI's `Value per share` line prints a RANGE (-14.13 to 77.08 for
    UBER_FY2024); 77.08 comes from the separate `Latest-period basis` line.
    Quoting a range's label around a single number is the point-estimate
    reading CLAUDE.md's seventh settled principle refuses, and it drifted into
    a file whose whole job is telling a reader what to expect."""
    check(f"run_valuation.py prints a '{ANCHOR_LABEL}' line",
          ANCHOR_LABEL in CLI.read_text(encoding="utf-8"))
    for doc in (README, CLAUDE, Path("data/README.md")):
        text = doc.read_text(encoding="utf-8")
        if "77.08" not in text:
            continue
        check(f"{doc} names the anchor's own label beside 77.08",
              ANCHOR_LABEL in text,
              "77.08 is the latest-period basis, not the 'Value per share' range")


def slug(heading: str) -> str:
    """GitHub's anchor for a markdown heading: lowercase, punctuation dropped,
    spaces hyphenated."""
    text = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s+", "-", text.strip())


def test_readme_links_into_claude_md_resolve():
    """A renamed heading leaves a link that goes nowhere. The "five 10-K
    facts" anchor outlived the heading it pointed at by two counts."""
    claude = CLAUDE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    anchors = {slug(h) for h in re.findall(r"^#+ (.+)$", claude, re.M)}
    links = re.findall(r"\(CLAUDE\.md#([\w-]+)\)", readme)
    check("README links into CLAUDE.md by anchor", bool(links))
    for link in links:
        check(f"CLAUDE.md#{link} is a heading that exists", link in anchors,
              "no heading in CLAUDE.md slugifies to that")


def test_the_needs_filings_marker_is_registered_and_used():
    """The marker name lives in three files. A typo in any one of them is
    silent: pytest warns about an unknown mark and runs the test anyway,
    which on a fresh clone is the FileNotFoundError this whole mechanism
    exists to remove."""
    check("tests/conftest.py exists", CONFTEST.is_file())
    if not CONFTEST.is_file():
        return
    conftest = CONFTEST.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    check("pyproject.toml registers the needs_filings marker",
          "needs_filings:" in pyproject)
    check("conftest.py skips on the needs_filings marker",
          "needs_filings" in conftest)
    check("conftest.py prints the skip count in the terminal summary",
          "pytest_terminal_summary" in conftest
          and "NOT verified by this run" in conftest)
    check("the workflow comment names the marker",
          "needs_filings" in workflow)

    marked = sum(len(re.findall(r"@pytest\.mark\.needs_filings", p.read_text(encoding="utf-8")))
                 for p in sorted(Path("tests").glob("test_*.py")))
    check(f"{marked} test functions carry the marker", marked > 0,
          "conftest.py's mechanism guards nothing if nothing is marked")


if __name__ == "__main__":
    print("Command lists:")
    commands = test_command_lists_are_identical()
    test_every_documented_script_exists(commands)
    test_prose_counts_match_the_command_list(commands)

    print("CI:")
    ci_scripts = test_ci_runs_only_scripts_that_exist_and_are_documented(commands)
    test_ci_coverage_claims_match_what_it_runs(commands, ci_scripts)

    print("Counts stated in two places:")
    test_no_workflow_needs_a_file_the_repository_does_not_ship()
    test_no_inert_workflow_sits_outside_the_workflows_directory()
    test_gate_count_is_not_stale()
    test_operating_model_docstring_matches_the_bridge()
    test_adr_count_matches_the_directory()
    test_uber_facts_count_agrees_everywhere()
    test_the_anchor_is_quoted_under_the_label_the_cli_prints()
    test_readme_links_into_claude_md_resolve()
    test_the_needs_filings_marker_is_registered_and_used()

    if failures:
        print(f"\n{len(failures)} documentation claim(s) no longer match the code:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print("\nAll documentation claims match the code.")
