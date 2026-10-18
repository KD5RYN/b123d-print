"""The DS-* rule IDs in docs/DESIGN_GUIDE.md and the code, AGENTS.md, the rubric and the style
files that cite them stay in step (like test_rules.py for BEST_PRACTICES)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs/DESIGN_GUIDE.md").read_text(encoding="utf-8")
DATA = ROOT / "src/b123d_print/data"
CITERS = {
    "code": "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")),
    "AGENTS.md": (DATA / "AGENTS.md").read_text(encoding="utf-8"),
    "rubric": (DATA / "design_review.md").read_text(encoding="utf-8"),
    "styles": "\n".join(p.read_text(encoding="utf-8") for p in (DATA / "styles").glob("*.toml")),
}
ID = r"DS-[A-Z]\d+"


def rules() -> dict[str, set[str]]:
    """ID -> its classes, from rows like `| DS-G1 | rule | evidence | kind | **m** + **r** | behavior |`."""
    out = {}
    for line in PAGE.splitlines():
        m = re.match(rf"\|\s*({ID})\s*\|", line)
        if m:
            cols = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]  # \| is a pipe in a cell
            out[m.group(1)] = set(re.findall(r"\*\*([mrid])\*\*", cols[4]))
    return out


RULES = rules()


def test_page_has_rules():
    assert len(RULES) > 30 and all(RULES.values()), "every DS rule row has a class"


def test_cited_ids_exist_and_are_not_dropped():
    for where, text in CITERS.items():
        cited = set(re.findall(ID, text))
        assert cited - set(RULES) == set(), f"{where} cites rules not in DESIGN_GUIDE.md"
        assert {i for i in cited if RULES[i] == {"d"}} == set(), f"{where} cites a dropped rule"


def test_metric_rules_are_computed():
    in_code = set(re.findall(ID, CITERS["code"]))
    missing = {i for i, c in RULES.items() if "m" in c} - in_code
    assert missing == set(), "class-m rules no metric or finding cites"


def test_every_threshold_cites_a_rule():
    from b123d_print.styles import THRESHOLDS

    assert all(rule in RULES for _, rule, _ in THRESHOLDS.values())


def test_agents_copies_match():
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8") == CITERS["AGENTS.md"]
