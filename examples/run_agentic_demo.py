"""Run the checked-in cross-dataset evidence demonstrations."""
import json
from pathlib import Path

from anomalyzer import analyze


ROOT = Path(__file__).parent / "agentic"


def summary(result):
    relationship = result.relationship_results[0]
    return {
        "relationship": relationship.relationship_id,
        "status": relationship.status,
        "triggered_samples": [
            item["index"] for method in relationship.methods
            for item in method.evidence if item["triggers"]],
        "criterion_violations": [
            item.index for item in relationship.assessments
            if item.classification == "criterion_violation"],
        "case_count": len(result.cases),
    }


def main():
    expected = json.loads((ROOT / "expected.json").read_text(encoding="utf-8"))
    failed = False
    for name, wanted in expected.items():
        request = json.loads((ROOT / name).read_text(encoding="utf-8"))
        result = analyze(request)
        actual = summary(result)
        if actual == wanted:
            print(f"PASS {name}: {json.dumps(actual, sort_keys=True)}")
        else:
            failed = True
            print(f"FAIL {name}: expected={wanted!r} actual={actual!r}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
