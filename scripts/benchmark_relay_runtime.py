"""Offline scheduling/checkpoint benchmark; never calls an external API."""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.relay_runtime import RelayRuntime, atomic_json, bounded_results


def jobs(count, langs):
    for start in range(0, count, 60):
        yield 'translate', {'target_languages': langs, 'rows': [
            {'request_key': str(i), 'cn': f'Reward number {i}'} for i in range(start, min(start + 60, count))]}
    for stage in ('review', 'audit'):
        for lang in langs:
            for start in range(0, count, 30):
                yield stage, {'rows': [{'review_key': str(i), 'lang': lang, 'current': f'Reward number {i}'}
                                      for i in range(start, min(start + 30, count))]}


def run(out, count=40000, workers=4, delay=.005):
    langs = ['EN', 'DE', 'FR', 'ES']
    out.mkdir(parents=True, exist_ok=True)
    batches = list(jobs(count, langs))
    baseline_dir = out / 'baseline'
    bounded_dir = out / 'bounded'
    baseline_dir.mkdir(exist_ok=True)
    bounded_dir.mkdir(exist_ok=True)
    def simulated_call():
        time.sleep(delay)
        return {'accepted': True}, {'usage': {'total_tokens': 1}}
    def baseline(item):
        index, (_, data) = item
        result, _ = simulated_call()
        atomic_json(baseline_dir / f'{index}.json', {'rows': data['rows'], 'result': result})
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(baseline, enumerate(batches)))
    old_seconds = time.perf_counter() - started
    runner = RelayRuntime(bounded_dir, limit=workers)
    def current(item):
        index, (stage, data) = item
        result = runner.request('mock', stage, data, simulated_call)
        atomic_json(bounded_dir / f'{index}.json', {'rows': data['rows'], 'result': result})
    started = time.perf_counter()
    failures = []
    for _, _, error in bounded_results(current, enumerate(batches), workers=workers):
        if error:
            failures.append(str(error))
    new_seconds = time.perf_counter() - started
    progress = runner.progress(force=True)
    started = time.perf_counter()
    accepted = sum(json.loads((bounded_dir / f'{i}.json').read_text(encoding='utf-8'))['result']['accepted'] for i in range(len(batches)))
    resume_seconds = time.perf_counter() - started
    report = {
        'mode': 'offline_simulation_not_model_speed', 'source_rows': count,
        'target_cells': count * len(langs), 'workers': workers, 'mock_latency_ms': delay * 1000,
        'baseline_requests': len(batches), 'new_requests': progress['requests'],
        'baseline_seconds': round(old_seconds, 3), 'new_seconds': round(new_seconds, 3),
        'added_scheduler_ms_per_request': round(1000 * max(0, new_seconds - old_seconds) / len(batches), 4),
        'accepted_batches_on_resume': accepted, 'resume_read_seconds': round(resume_seconds, 3),
        'peak_active': progress['peak_active'], 'failures': failures,
    }
    atomic_json(out / 'benchmark.json', report)
    print(json.dumps(report, indent=2))
    return 1 if failures or accepted != len(batches) or progress['peak_active'] > 5 else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=40000)
    parser.add_argument('--workers', type=int, choices=range(1, 6), default=4)
    args = parser.parse_args()
    raise SystemExit(run(args.output_dir, args.rows, args.workers))
