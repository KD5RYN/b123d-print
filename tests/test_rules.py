"""The rule IDs in docs/BEST_PRACTICES.md and the code and AGENTS.md that cite them stay in step.

Each rule row in the page is `| W1 | rule | value | evidence | P | **a** | behavior |`. Code cites
a rule as `BP-W1`, AGENTS.md as `[W1]` (or `[W1, W2]`), coupons in their docstrings as `BP-W1`.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs/BEST_PRACTICES.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "src/b123d_print/data/AGENTS.md").read_text(encoding="utf-8")
CHECKS = (ROOT / "src/b123d_print/checks.py").read_text(encoding="utf-8")
EXAMPLES = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src/b123d_print/examples").rglob("*.py"))
CODE = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py"))


def rules() -> dict[str, set[str]]:
    """ID -> its classes, e.g. {"O1": {"a", "c"}}."""
    out = {}
    for line in PAGE.splitlines():
        m = re.match(r"\|\s*([A-Z]\d+)\s*\|", line)
        if m:
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            out[m.group(1)] = set(re.findall(r"\*\*([abcd])\*\*", cols[5]))
    return out


RULES = rules()


def agents_ids() -> set[str]:
    return {i.strip() for g in re.findall(r"\[([A-Z]\d+(?:,\s*[A-Z]\d+)*)\]", AGENTS) for i in g.split(",")}


def pending() -> set[str]:
    m = re.search(r"\*\*Not yet implemented\*\*[^:]*:\s*([A-Z0-9, ]+)\.", PAGE)
    return {x.strip() for x in m.group(1).split(",")} if m else set()


def test_page_has_rules():
    assert len(RULES) > 60 and all(RULES.values()), "every rule row has a class"


def test_cited_ids_exist_and_are_not_dropped():
    cited = set(re.findall(r"BP-([A-Z]\d+)", CODE)) | agents_ids()
    assert cited - set(RULES) == set(), "cited but not in docs/BEST_PRACTICES.md"
    dropped = {i for i in cited if RULES[i] == {"d"}}
    assert dropped == set(), "class-d (dropped) rules must not be cited"


def test_automatable_rules_have_checks():
    in_checks = set(re.findall(r"BP-([A-Z]\d+)", CHECKS))
    missing = {i for i, c in RULES.items() if "a" in c} - in_checks - pending()
    assert missing == set(), "class-a rules with no check citing them (or add them to 'Not yet implemented')"
    assert pending() & in_checks == set(), "implemented now: take them off the 'Not yet implemented' list"


def test_guidance_rules_are_in_agents_md():
    missing = {i for i, c in RULES.items() if "b" in c} - agents_ids()
    assert missing == set(), "class-b rules missing from AGENTS.md"


def test_calibration_rules_are_covered():
    covered = agents_ids() | set(re.findall(r"BP-([A-Z]\d+)", EXAMPLES))
    missing = {i for i, c in RULES.items() if "c" in c} - covered
    assert missing == set(), "class-c rules neither in AGENTS.md nor in a coupon"


def test_provisional_rules_are_labeled():
    """Single-source rules appear in AGENTS.md only on a 'Provisional' line."""
    prov = {i for i in RULES if re.search(rf"^\|\s*{i}\s*\|.*\(provisional\)", PAGE, re.M)}
    assert prov
    for i in prov:
        line = next(ln for ln in AGENTS.split("\n- ") if f"[{i}]" in ln or re.search(rf"\[[^\]]*\b{i}\b[^\]]*\]", ln))
        assert line.startswith("Provisional"), f"{i} is single-source: label it provisional in AGENTS.md"
