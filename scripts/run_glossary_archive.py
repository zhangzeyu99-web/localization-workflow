"""Archive explicitly superseded glossaries; defaults to a read-only plan."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.glossary_archive import archive_glossaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--old', type=Path, action='append', required=True)
    parser.add_argument('--expected-current-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = archive_glossaries(project_dir=args.project_dir, current=args.current,
                               previous=args.old, expected_current_sha256=args.expected_current_sha256,
                               apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
