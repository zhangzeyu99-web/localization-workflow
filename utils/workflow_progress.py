"""Accepted-work progress and conditional delivery estimates; no model calls."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any


MODEL_PHASES = ('api_translate', 'subagent_review', 'controller_merge')


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else result.astimezone()
    except ValueError:
        return None


def update_progress(manifest: dict, phase: str, *, total: int, accepted: int,
                    reused: int, seconds: float) -> None:
    if (any(type(value) is not int for value in (total, accepted, reused))
            or not 0 <= reused <= accepted <= total or not math.isfinite(seconds) or seconds < 0):
        raise ValueError('invalid accepted progress counters')
    manifest.setdefault('phase_progress', {})[phase] = {
        'total_cells': total, 'accepted_cells': accepted, 'reused_cells': reused,
        'active_seconds': round(seconds, 3),
        'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    }


def delivery_status(manifest: dict[str, Any], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must have a timezone')
    phases = manifest.get('phase_status', {})
    progress = manifest.get('phase_progress', {})
    pending = [name for name in manifest.get('critical_path', [])
               if phases.get(name) not in {'done', 'skipped'}]
    complete = manifest.get('status') == 'complete' and not pending
    blockers = list(manifest.get('blockers') or [])
    for event in reversed(manifest.get('phase_events', [])):
        if event.get('event') == 'failed' and phases.get(event.get('phase')) == 'failed':
            blockers.append({'phase': event['phase'], 'reason': event.get('error', 'phase failed')})
            break
    running = [name for name in pending if phases.get(name) == 'running']
    failed = [name for name in pending if phases.get(name) == 'failed']
    if failed and not blockers:
        blockers.append({'phase': failed[0], 'reason': 'phase failed; inspect its diagnostic receipt'})
    current = next(iter(failed or running or pending), 'complete' if complete else 'awaiting_completion_record')
    sample_rates = {}
    for name, sample in progress.items():
        fresh = sample.get('accepted_cells', 0) - sample.get('reused_cells', 0)
        seconds = sample.get('active_seconds', 0)
        if fresh > 0 and seconds > 0:
            sample_rates[name] = seconds / fresh
    expected = int(manifest.get('preflight', {}).get('estimated_target_cells', 0))
    estimates, assumptions, unmeasured = {}, [], []
    for name in MODEL_PHASES:
        if name not in pending:
            continue
        sample = progress.get(name, {})
        remaining = max(0, sample.get('total_cells', expected) - sample.get('accepted_cells', 0))
        if not remaining:
            estimates[name] = 0
            continue
        rate = sample_rates.get(name)
        if rate is None and sample_rates:
            # A proxy is visible and deliberately conservative until this role runs.
            rate = max(sample_rates.values()) * (2 if name != 'api_translate' else 1)
            assumptions.append(f'{name}: provisional rate from another measured role')
        if rate is None:
            unmeasured.append(name)
        else:
            estimates[name] = rate * remaining
    local_pending = [name for name in pending if name not in MODEL_PHASES
                     and name not in {'preflight', 'api_smoke', 'glossary_enrichment'}]
    budget = manifest.get('reporting', {}).get('delivery_reserve_seconds')
    if budget is None:
        budget = 900 if expected > 20000 else 120
        if local_pending:
            assumptions.append('unmeasured local QA/export/acceptance reserve; excludes new semantic repairs')
    if not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0:
        raise ValueError('delivery_reserve_seconds must be a finite nonnegative number')
    base = sum(estimates.values())
    reserve = budget if local_pending else 0
    remaining_range = None if unmeasured else [math.ceil(base * .75 + reserve),
                                              math.ceil(base * 1.75 + reserve * 3)]
    if complete:
        remaining_range = [0, 0]
    finish = None
    if remaining_range is not None and not blockers:
        finish = [(now + timedelta(seconds=seconds)).isoformat(timespec='seconds')
                  for seconds in remaining_range]
    due = _time(manifest.get('reporting', {}).get('next_report_at'))
    overdue = bool(due and now >= due)
    return {
        'complete': complete, 'completion_scope': 'native_pipeline_only',
        'formal_delivery_requires': ['publication', 'native_excel_acceptance', 'visual_acceptance'],
        'current_phase': current, 'remaining_phases': pending,
        'accepted_progress': progress, 'blockers': blockers,
        'estimated_active_remaining_seconds': remaining_range,
        'estimated_completion_at': finish, 'unmeasured_phases': unmeasured,
        'assumptions': assumptions, 'waiting_time_included': False,
        'report_required': not complete or overdue, 'report_overdue': overdue,
        'reason': ('complete' if complete else 'blocked; waiting duration is unknown' if blockers
                   else 'calibrating first accepted batch' if unmeasured
                   else 'processing; delivery gates still pending'),
        'next_action': ('verify project publication and native Excel acceptance before claiming delivery' if complete else
                        'diagnose blockers; advance independent ready queue items' if blockers else
                        'report conditional ETA and next checkpoint; keep current owner running'),
    }


def queue_status(queue: dict) -> dict:
    """Choose independent work without equating a missing PID with an idle API."""
    items = queue.get('items', [])
    completed = {item['id'] for item in items if item.get('state') == 'complete'}
    active = [item['id'] for item in items if item.get('state') == 'running']
    ready, blocked, local = [], [], []
    for item in items:
        if item['id'] in completed or item['id'] in active:
            continue
        if item.get('state') in {'canonical_complete', 'canon_complete', 'awaiting_visual_acceptance'}:
            local.append(item['id'])
            continue
        dependencies = set(item.get('depends_on', [])) - completed
        reasons = list(item.get('blockers') or [])
        if dependencies or reasons or item.get('pending_source_ids') or item.get('state') not in {'pending', 'queued', 'ready'}:
            blocked.append({'id': item['id'], 'dependencies': sorted(dependencies),
                            'reasons': reasons, 'pending_source_ids': item.get('pending_source_ids', [])})
        else:
            ready.append(item['id'])
    return {'active_items': active, 'ready_items': ready, 'blocked_items': blocked,
            'local_acceptance_items': local,
            'next_runnable': None if active or not ready or str(queue.get('state', '')).lower() in {'paused', 'complete'} else ready[0],
            'requires_live_process_check': True, 'starts_processes': False,
            'completion_claim_allowed': False}
