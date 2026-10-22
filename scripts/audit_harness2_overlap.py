#!/usr/bin/env python3
"""Read-only inventory of possible duplicate agents, controllers and memories.

Usage: python scripts/audit_harness2_overlap.py
       python scripts/audit_harness2_overlap.py --json
No dependencies, imports of project modules, network calls or file mutations.
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "build", "dist"}
TOPICS = {
    "memory": ("memory", "remember", "episodic", "vector_store"),
    "planning": ("planner", "planning", "orchestrator", "decision_engine", "jde"),
    "desktop_control": ("cua", "computer_use", "desktop", "controller", "pyautogui", "pywinauto", "sai"),
    "harness": ("harness2", "harness", "skills", "subagent"),
}

def project_files():
    for path in ROOT.rglob("*.py"):
        if not any(part in IGNORED for part in path.relative_to(ROOT).parts):
            yield path

def audit():
    files = list(project_files())
    basename_groups = defaultdict(list)
    topics = defaultdict(list)
    imports = defaultdict(list)
    errors = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        basename_groups[path.name].append(relative)
        matched = [topic for topic, words in TOPICS.items() if any(word in relative.lower() for word in words)]
        for topic in matched:
            topics[topic].append(relative)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({"path": relative, "error": str(exc)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.name.split(".")[0]].append(relative)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports[node.module.split(".")[0]].append(relative)
    duplicates = {name: paths for name, paths in basename_groups.items() if len(paths) > 1 and name != "__init__.py"}
    return {
        "files_scanned": len(files),
        "topic_candidates": dict(topics),
        "duplicate_basenames": duplicates,
        "imported_root_modules": {k: sorted(set(v)) for k, v in imports.items()},
        "parse_errors": errors,
        "warning": "Candidates are not proven redundancies. Do not delete until import/runtime/test verification.",
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Python files scanned: {result['files_scanned']}")
        for topic, paths in result["topic_candidates"].items():
            print(f"\n[{topic}] {len(paths)} candidates")
            for path in paths:
                print(f"  {path}")
        print("\nDuplicate basenames (NOT automatic deletions):")
        for name, paths in result["duplicate_basenames"].items():
            print(f"  {name}: {', '.join(paths)}")
        if result["parse_errors"]:
            print(f"\nUnreadable/unparseable files: {len(result['parse_errors'])}")
        print("\n" + result["warning"])

if __name__ == "__main__":
    main()
