"""Archive explicitly superseded root glossaries after delivery acceptance."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_glossaries(*, project_dir: Path, current: Path, previous: list[Path],
                       expected_current_sha256: str, apply: bool = False) -> dict:
    root = project_dir.resolve(strict=True)

    def root_file(path: Path) -> Path:
        if path.is_symlink():
            raise ValueError('symlink glossary is not allowed')
        resolved = path.resolve(strict=True)
        if resolved.parent != root or not resolved.is_file() or resolved.suffix.lower() != '.xlsx':
            raise ValueError('glossary must be an xlsx directly inside the project root')
        return resolved

    current = root_file(current)
    old = [root_file(path) for path in previous]
    if not old or len(set(old)) != len(old) or current in old:
        raise ValueError('previous glossaries must be unique and exclude the current glossary')
    if sha256(current) != expected_current_sha256.lower():
        raise ValueError('accepted current glossary hash mismatch')
    with ZipFile(current) as archive:
        if archive.testzip() or 'xl/workbook.xml' not in archive.namelist():
            raise ValueError('current glossary is not a valid xlsx container')
    archive_root = root / '_archive' / 'glossaries'
    if not archive_root.resolve().is_relative_to(root):
        raise ValueError('archive directory escapes the project root')
    run = archive_root / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8])
    result = {'status': 'planned', 'current': str(current),
              'current_sha256': expected_current_sha256.lower(),
              'archive_dir': str(run), 'files': [
                  {'source': str(path), 'destination': str(run / path.name),
                   'sha256': sha256(path), 'status': 'pending'} for path in old]}
    if not apply:
        return result
    run.mkdir(parents=True, exist_ok=False)
    receipt = run / 'archive_receipt.json'

    def save() -> None:
        temporary = run / 'archive_receipt.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(receipt)

    # Preserve relocation evidence even if a later source is locked or has changed.
    save()
    try:
        for item in result['files']:
            source, destination = Path(item['source']), Path(item['destination'])
            if sha256(current) != result['current_sha256'] or sha256(source) != item['sha256']:
                raise ValueError('glossary changed after archive preflight')
            if destination.exists():
                raise ValueError('archive destination already exists')
            source.rename(destination)
            if sha256(destination) != item['sha256']:
                raise ValueError('archived glossary hash mismatch')
            item['status'] = 'archived'
            save()
        result['status'] = 'complete'
    except Exception:
        result['status'] = 'incomplete'
        save()
        raise
    save()
    return {**result, 'receipt': str(receipt)}
