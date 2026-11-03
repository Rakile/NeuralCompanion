"""Audit authored coverage without loading addons, models or user settings.

Run from the repository root: python -B tools/check_tutorial_coverage.py
Authored coverage is deliberately distinct from live runtime verification.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import tutorial_catalog, tutorial_scope
from core.tutorial_course import prepare_tutorial
from core.tutorial_coverage import audit_detailed_guides


def main() -> int:
    catalog = tutorial_catalog.list_tutorials()
    payloads = {item["id"]: tutorial_catalog.load_tutorial(item["id"]) for item in catalog}
    ids = [item["id"] for item in catalog]
    manifests = {json.loads(path.read_text(encoding="utf-8-sig"))["id"]
                 for path in (ROOT / "addons").glob("*/addon.json")}
    owners = json.loads((ROOT / "tutorials/scoped/owners.json").read_text(encoding="utf-8"))["owners"]
    inventoried = {owner["manifest_id"] for owner in owners}
    authored = {item["scope"].get("owner_addon") for item in catalog
                if item["kind"] in {"overview", "section"}}
    errors: list[str] = []
    errors.extend(audit_detailed_guides(payloads))
    if len(ids) != len(set(ids)):
        errors.append("Duplicate tutorial IDs")
    for missing in sorted(manifests - authored):
        errors.append("Missing authored addon guide: " + missing)
    for difference in sorted(manifests ^ inventoried):
        errors.append("Inventory differs from installed source manifests: " + difference)
    for item in catalog:
        errors.extend(f"{item['id']}: {error}" for error in item["validation_errors"])
        payload = tutorial_catalog.load_tutorial(item["id"])
        try:
            prepare_tutorial(payload, tutorial_catalog.load_tutorial)
        except ValueError as error:
            errors.append(f"{item['id']}: {error}")
        for child in item["children"]:
            if child not in ids:
                errors.append(f"{item['id']}: missing child {child}")
    for owner in owners:
        for page in owner["pages"]:
            guide = tutorial_catalog.load_tutorial(page["guide_id"])
            if not guide or guide.get("scope") != page["scope"]:
                errors.append("Missing or changed inventoried page: " + page["guide_id"])
    first_chat_hash = hashlib.sha256((ROOT / "tutorials/first_run.json").read_bytes()).hexdigest()
    if first_chat_hash != "e415f566e499921136e9201098d72efb97617ed109928fd6f96c5ba947e3645c":
        errors.append("First Chat changed")
    print(json.dumps({"addon_manifests": len(manifests), "inventoried": len(inventoried),
                      "authored_addons": len(manifests & authored),
                      "tutorials": len(catalog), "kinds": dict(Counter(item["kind"] or "legacy/remote" for item in catalog)),
                      "visible_tutorials": sum(not item["hidden"] for item in catalog),
                      "preserved_overview_aliases": sum(item["hidden"] for item in catalog),
                      "course_roots": sum("course_chapters" in tutorial_catalog.load_tutorial(item["id"]) for item in catalog),
                      "linked_full_walkthroughs": sum(bool(payload.get("contextual_guides")) for payload in payloads.values()),
                      "runtime_verified_addons": sum(owner["runtime_verified"] for owner in owners),
                      "first_chat_sha256": first_chat_hash, "errors": errors}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
