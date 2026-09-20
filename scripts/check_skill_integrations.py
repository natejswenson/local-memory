#!/usr/bin/env python3
"""Verify all skill policies and invented cases against the real hub validator.

Read-only across repositories; --snapshot explicitly writes reviewed synthetic
cases into this repository for isolated CI. No plugin code or user data is run.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.skill_contract import policies, validate_value  # noqa: E402 — local checkout import


def check(repo):
    found = {
        p.name
        for p in (repo / "skills").iterdir()
        if (p / "skills" / p.name / "SKILL.md").exists()
    }
    assert found == set(policies()), "Skill inventory mismatch"
    rows = []
    count = 0
    for skill, expected in policies().items():
        folder = repo / "skills" / skill / "skills" / skill
        actual = json.loads((folder / "memory-policy.json").read_text())
        assert actual == expected, f"{skill}: policy mismatch"
        cases = json.loads((folder / "references/local-memory-cases.json").read_text())
        assert cases["skill"] == skill and set(cases) == {
            "skill",
            "allowed",
            "rejected",
        }, f"{skill}: invalid cases"
        assert cases["rejected"], f"{skill}: no negative cases"
        if expected["keys"]:
            assert {c["key"] for c in cases["allowed"]} == set(expected["keys"]), (
                f"{skill}: incomplete positive coverage"
            )
        else:
            assert not cases["allowed"], f"{skill}: deferred positive case"
        for case in cases["allowed"]:
            validate_value(skill, case["key"], case["value"])
            count += 1
        for case in cases["rejected"]:
            try:
                validate_value(skill, case["key"], case["value"])
            except (ValueError, TypeError):
                pass
            else:
                raise AssertionError(
                    f"{skill}: rejection case accepted for {case['key']}"
                )
            count += 1
        rows.append(cases)
        package = folder / "package.json"
        if package.exists():
            files = json.loads(package.read_text()).get("files")
            if files is not None:
                assert "memory-policy.json" in files, (
                    f"{skill}: missing policy in package files"
                )
    return rows, count


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skills-repo", type=Path, required=True)
    p.add_argument("--snapshot", action="store_true")
    a = p.parse_args()
    rows, count = check(a.skills_repo)
    if a.snapshot:
        target = ROOT / "tests/fixtures/skill-memory-cases.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"skills": len(rows), "validator_cases": count, "passed": True}))
