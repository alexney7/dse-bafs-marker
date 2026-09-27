"""Read-only library inventory lookup; existence is not content verification."""
import argparse
import json
import os
from pathlib import Path


def inspect(root, catalog, year=None, role=None, query=None):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Library root is missing or inaccessible')
    rows = []
    for item in catalog['files']:
        if year is not None and item.get('year') != year:
            continue
        if role and item.get('role') != role:
            continue
        if query and query.casefold() not in item['path'].casefold():
            continue
        target = (root / item['path']).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Inventory path escapes library root')
        rows.append({**item, 'absolute_path': str(target), 'exists': target.is_file()})
    return {'root': str(root), 'matched': len(rows),
            'missing_files': sum(not r['exists'] for r in rows),
            'files': rows, 'known_content_gaps': catalog['known_content_gaps']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--year', type=int)
    parser.add_argument('--role', choices=['textbook', 'sample', 'paper', 'mark-scheme', 'compendium', 'performance-report'])
    parser.add_argument('--query')
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    root = args.root or os.environ.get('BAFS_MARKER_LIBRARY')
    config = skill / 'library.local.json'
    if root is None and config.exists():
        root = json.loads(config.read_text(encoding='utf-8-sig')).get('root')
    if not root:
        parser.error('Provide --root, BAFS_MARKER_LIBRARY, or library.local.json')
    catalog = json.loads((skill/'references/library-index.json').read_text(encoding='utf-8'))
    try:
        result = inspect(root, catalog, args.year, args.role, args.query)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['missing_files'] or not result['matched'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
