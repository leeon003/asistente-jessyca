#!/usr/bin/env python3
"""Read-only AST inventory of tracked Python files; never imports the application.

Usage: python scripts/audit_repository.py > inventory.json
Static reachability includes conditional imports; it is NOT runtime activation or
proof of obsolescence. Dynamic loads and external consumers require manual review.
"""
from __future__ import annotations
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ["main.py", "interfaces/modo_texto.py", "interfaces/modo_voz.py",
               "interfaces/mobile_api/app.py", "interfaces/webui_bridge/app.py"]


def audit(root: Path = ROOT) -> dict:
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split('\0')
    paths = [p for p in paths if p and (root / p).is_file()]
    modules, hashes = defaultdict(list), defaultdict(list)
    trees, imports, edges = {}, {}, {}
    errors, duplicates, dynamic = [], [], []
    for path in paths:
        if not path.endswith('.py'):
            continue
        source = (root / path).read_text(encoding='utf-8-sig')
        hashes[hashlib.sha256(source.encode()).hexdigest()].append(path)
        modules[path[:-3].replace('/', '.').removesuffix('.__init__')].append(path)
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError as exc:
            errors.append(dict(path=path, line=exc.lineno, error=exc.msg))
    # Python resolves an ordinary package ahead of a same-named .py module.
    resolved = {key: next((p for p in group if p.endswith('/__init__.py')), group[0])
                for key, group in modules.items()}
    roots = {key.split('.')[0] for key in modules}
    external = defaultdict(set)
    for path, tree in trees.items():
        rows = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                rows.extend(dict(module=a.name, line=node.lineno, kind='import') for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    pkg = path[:-3].replace('/', '.').split('.')[:-1]
                    base = '.'.join(pkg[:len(pkg)-node.level+1] + ([base] if base else []))
                rows.append(dict(module=base, line=node.lineno, kind='from', names=[a.name for a in node.names]))
            elif isinstance(node, ast.ClassDef):
                assigned = defaultdict(list)
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        assigned[item.target.id].append(item.lineno)
                duplicates.extend(dict(path=path, cls=node.name, field=k, lines=v)
                                  for k,v in assigned.items() if len(v)>1)
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name.endswith(('import_module', '__import__', 'spec_from_file_location', 'entry_points')):
                    dynamic.append(dict(path=path, line=node.lineno, call=name))
        imports[path] = rows
        destinations = set()
        for row in rows:
            module = row['module']; parts = module.split('.')
            for index in range(1, len(parts)+1):
                target = resolved.get('.'.join(parts[:index]))
                if target and (target.endswith('/__init__.py') or index == len(parts)):
                    destinations.add(target)
            for name in row.get('names', []):
                target = resolved.get(module + '.' + name)
                if target:
                    destinations.add(target)
            if parts[0] and parts[0] not in sys.stdlib_module_names and parts[0] not in roots:
                external[parts[0]].add(path)
        edges[path] = sorted(destinations)
    seen, todo = set(), ENTRYPOINTS[:]
    while todo:
        path = todo.pop()
        if path not in seen:
            seen.add(path); todo.extend(edges.get(path, []))
    return dict(
        tracked_files=len(paths), python_files=len(trees)+len(errors),
        parse_errors=errors,
        module_collisions={k:v for k,v in modules.items() if len(v)>1},
        duplicate_class_fields=duplicates,
        identical_files=[v for v in hashes.values() if len(v)>1 and any((root/p).stat().st_size>100 for p in v)],
        external_import_candidates={k:sorted(v) for k,v in sorted(external.items())},
        dynamic_load_sites=dynamic, entrypoints=ENTRYPOINTS,
        statically_reachable=sorted(seen),
        not_statically_reachable=sorted(set(trees)-seen), imports=imports, edges=edges,
        limitations=__doc__,
    )

if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
