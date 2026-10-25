"""Inventory every tracked Python file without importing or executing the application."""
from __future__ import annotations
import ast
import json
import subprocess
from pathlib import Path


def inventory(root: Path) -> dict:
    paths = subprocess.check_output(['git', 'ls-files', '*.py'], cwd=root, text=True).splitlines()
    entries = []
    for name in sorted(paths):
        source = (root / name).read_text(encoding='utf-8-sig')
        entry = {'path': name, 'lines': len(source.splitlines()), 'imports': [], 'error': None}
        try:
            tree = ast.parse(source, filename=name)
            entry['imports'] = sorted({
                node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names})
        except SyntaxError as exc:
            entry['error'] = str(exc)
        entries.append(entry)
    return {'scope': 'Static syntax/import inventory, not a semantic audit of every line',
            'files': len(entries), 'lines': sum(e['lines'] for e in entries),
            'syntax_errors': sum(e['error'] is not None for e in entries), 'entries': entries}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    result = inventory(root)
    destination = root / 'docs/audits/conversation_inventory.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({k: v for k, v in result.items() if k != 'entries'})
