"""Prepare extraction/review handoff or accept a completed additive glossary."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.glossary_enrichment import accept_glossary, fingerprint, prepare_request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--input', type=Path, action='append', required=True)
    prepare.add_argument('--term-base', type=Path, required=True)
    prepare.add_argument('--target-langs', required=True)
    prepare.add_argument('--glossary-workflow', type=Path, required=True)
    prepare.add_argument('--work-dir', type=Path, required=True)
    prepare.add_argument('--review-file', type=Path)
    accept = sub.add_parser('accept')
    accept.add_argument('--request', type=Path, required=True)
    accept.add_argument('--reviewed', type=Path, required=True)
    accept.add_argument('--updated-glossary', type=Path, required=True)
    accept.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
        elif isinstance(value, list) and value and isinstance(value[0], Path):
            setattr(args, name, [path.resolve() for path in value])
    if args.command == 'prepare':
        entry = args.glossary_workflow / 'scripts' / 'export_glossary_candidates.py'
        if not entry.is_file():
            raise ValueError(f'glossary extraction entry not found: {entry}')
        args.work_dir.mkdir(parents=True, exist_ok=True)
        candidates = args.work_dir / 'candidates.json'
        monitored = [*args.input, args.term_base, *([args.review_file] if args.review_file else [])]
        before = [fingerprint(p) for p in monitored]
        command = [sys.executable, '-X', 'utf8', str(entry)]
        for path in args.input:
            command.extend(['--input', str(path)])
        command.extend(['--existing-glossary', str(args.term_base), '--target-langs', args.target_langs,
                        '--output', str(candidates)])
        if args.review_file:
            command.extend(['--review-file', str(args.review_file)])
        result = subprocess.run(command, cwd=args.glossary_workflow, capture_output=True, text=True, encoding='utf-8')
        (args.work_dir / 'extraction.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise ValueError('glossary extraction failed; see extraction.log')
        if before != [fingerprint(p) for p in monitored]:
            raise ValueError('input drift during glossary extraction')
        data = prepare_request(inputs=args.input, term_base=args.term_base,
                               target_langs=args.target_langs.split(','), candidates=candidates,
                               output=args.work_dir / 'request.json')
        print(json.dumps({'status': data['status'], 'candidates': str(candidates),
                          'request': str(args.work_dir / 'request.json')}))
    else:
        data = accept_glossary(request=args.request, reviewed=args.reviewed,
                               updated=args.updated_glossary, output=args.output)
        print(json.dumps({'status': data['status'], 'approved_terms': data['approved_terms'],
                          'receipt': str(args.output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
