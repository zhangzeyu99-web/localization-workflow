from __future__ import annotations

import io
import json
import tempfile
import subprocess
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook, load_workbook

from utils.large_text_multilingual_executor import OpenAICompatibleClient, _execute_batch, _cached_requests
from utils.large_text_multilingual_pipeline import run_pipeline, resume_pipeline
from utils.large_text_multilingual_proofread import _pid_is_running
from utils.relay_runtime import (
    FatalRelayError, IncompletePhase, RelayRuntime, RequestBudgetExceeded,
    ResponseTooLarge, bounded_results, classify_error, concurrency, task_lock,
)


@pytest.fixture
def tmp_path():
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


def runtime(path=None, **kwargs):
    return RelayRuntime(path, backoff_base=0, cooldown_seconds=0, jitter=lambda: 0, **kwargs)


def payload(key="a"):
    return {"rows": [{"request_key": key, "cn": "Reward"}], "target_languages": ["EN"]}


def test_process_liveness_probe_does_not_signal_child():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        assert _pid_is_running(child.pid)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert not _pid_is_running(child.pid)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows query permissions')
def test_windows_liveness_access_denied_keeps_lock_owner_live():
    with patch('ctypes.WinDLL') as library, patch('ctypes.get_last_error', return_value=5):
        library.return_value.OpenProcess.return_value = None
        assert _pid_is_running(123456)
    with patch('ctypes.WinDLL') as library, patch('ctypes.get_last_error', return_value=87):
        library.return_value.OpenProcess.return_value = None
        assert not _pid_is_running(123456)


def test_hard_cap_and_shared_roles(tmp_path):
    from utils.relay_runtime import MAX_API_CONCURRENCY

    for invalid in (0, MAX_API_CONCURRENCY + 1, 20):
        with pytest.raises(ValueError):
            concurrency(invalid)
    assert concurrency(MAX_API_CONCURRENCY) == MAX_API_CONCURRENCY
    runner = runtime(tmp_path, limit=5)
    def work(index):
        def send():
            time.sleep(.005)
            return {}, {"usage": {"total_tokens": 2}}
        return runner.request("relay", ["translate", "review", "audit"][index % 3], payload(str(index)), send)
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(work, range(100)))
    assert runner.peak_active == 5
    assert runner.requests == 100 and runner.retries == 0
    assert runner.usage["total_tokens"] == 200


def test_retry_budget_survives_restart_and_explicit_reset(tmp_path):
    runner = runtime(tmp_path)
    calls = []
    def fail():
        calls.append(1)
        raise TimeoutError("secret should not be logged")
    with pytest.raises(RuntimeError):
        runner.request("model", "translate", payload(), fail)
    assert len(calls) == 3
    restored = runtime(tmp_path)
    with pytest.raises(RequestBudgetExceeded):
        restored.request("model", "translate", payload(), fail)
    assert len(calls) == 3
    restored = runtime(tmp_path, retry_failed=True)
    assert restored.request("model", "translate", payload(), lambda: ({"ok": True}, {})) == {"ok": True}
    assert "secret" not in (tmp_path / "relay_requests.jsonl").read_text(encoding="utf-8")


def test_rate_limit_and_auth_are_not_split_or_unbounded(tmp_path):
    runner = runtime(tmp_path)
    calls = []
    def send():
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("https://example.invalid", 429, "rate", {"Retry-After": "0"}, io.BytesIO(b'{}'))
        return {"ok": True}, {}
    runner.request("relay", "review", payload(), send)
    assert len(calls) == 2 and runner.effective_limit == 2
    error = urllib.error.HTTPError("https://example.invalid", 401, "auth", {}, io.BytesIO(b'secret'))
    with pytest.raises(FatalRelayError):
        runner.request("relay", "audit", payload(), lambda: (_ for _ in ()).throw(error))
    before = runner.requests
    with pytest.raises(FatalRelayError):
        runner.request("relay", "audit", payload('new'), send)
    assert runner.requests == before


def test_http_classification():
    for code in (401, 403, 402, 400, 404):
        assert isinstance(classify_error(urllib.error.HTTPError('url', code, 'x', {}, None)), FatalRelayError)
    quota = urllib.error.HTTPError('url', 429, 'x', {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))
    assert isinstance(classify_error(quota), FatalRelayError)
    with pytest.raises(ResponseTooLarge):
        classify_error(urllib.error.HTTPError('url', 413, 'x', {}, None))


@pytest.mark.parametrize('code', ['daily_limit_exceeded', 'daily_quota_exceeded', 'insufficient_balance'])
def test_daily_quota_is_fatal_and_never_retried(tmp_path, code):
    runner = runtime(tmp_path)
    def send():
        body = json.dumps({'error': {'code': code, 'message': 'PRIVATE'}}).encode()
        raise urllib.error.HTTPError('url', 429, 'quota', {}, io.BytesIO(body))
    with pytest.raises(FatalRelayError):
        runner.request('relay', 'review', payload(), send)
    with pytest.raises(FatalRelayError):
        runner.request('relay', 'audit', payload('next'), send)
    assert runner.requests == 1 and runner.retries == 0
    progress = json.loads((tmp_path / 'relay_progress.json').read_text(encoding='utf-8'))
    assert progress['stop_reason'] == 'balance'
    assert 'PRIVATE' not in (tmp_path / 'relay_requests.jsonl').read_text(encoding='utf-8')


@pytest.mark.parametrize('body', [
    {'code': 1, 'message': '当天可用额度已达到上限,当前限额:40000 / Day', 'data': None},
    {'error': {'code': 'insufficient_quota', 'message': 'PRIVATE provider detail'}},
    {'error': {'message': 'Daily quota exceeded: PRIVATE provider detail'}},
])
def test_http_success_quota_error_stops_all_roles_without_retry(tmp_path, body):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'base_url': 'https://example.invalid', 'model': 'mock'}), encoding='utf-8')
    client = OpenAICompatibleClient(config, runtime=runtime(tmp_path))
    with patch('urllib.request.urlopen', side_effect=lambda *a, **k: io.BytesIO(json.dumps(body).encode('utf-8'))) as send:
        with pytest.raises(FatalRelayError, match='quota'):
            client._chat_json('Test', payload(), stage='audit')
        with pytest.raises(FatalRelayError, match='quota'):
            client._chat_json('Test', payload('new'), stage='translate')
    assert send.call_count == 1
    assert client.runtime.retries == 0
    assert 'PRIVATE' not in (tmp_path / 'relay_requests.jsonl').read_text(encoding='utf-8')


def test_valid_response_mentioning_quota_is_not_a_business_error(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'base_url': 'https://example.invalid', 'model': 'mock'}), encoding='utf-8')
    client = OpenAICompatibleClient(config, runtime=runtime(tmp_path))
    body = {'choices': [{'message': {'content': '{"text":"Daily quota exceeded"}'}}]}
    with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(body).encode('utf-8'))):
        assert client._chat_json('Test', payload()) == {'text': 'Daily quota exceeded'}


def test_bounded_queue_and_failure_isolation():
    yielded = []
    def jobs():
        for index in range(100):
            yielded.append(index)
            yield index
    def work(index):
        if index == 2:
            raise ValueError('one bad cell')
        return index
    results = bounded_results(work, jobs(), workers=4)
    first = next(results)
    assert len(yielded) <= 8
    all_results = [first, *results]
    assert len(all_results) == 100
    assert sum(error is not None for _, _, error in all_results) == 1


def test_task_lock_rejects_duplicate_owner_and_releases(tmp_path):
    with task_lock(tmp_path):
        with pytest.raises(RuntimeError, match='already running'):
            with task_lock(tmp_path):
                pass
    assert not (tmp_path / 'task.lock').exists()


def test_service_outage_stops_before_more_requests():
    runner = runtime(clock=lambda: 901)
    runner.outage_started = 0
    with pytest.raises(FatalRelayError, match='15 minutes'):
        runner.request('relay', 'review', payload(), lambda: ({}, {}))
    assert runner.requests == 0


def test_process_termination_resumes_saved_cells_and_reclaims_stale_lock(tmp_path):
    code = r'''
import json, sys, time
from pathlib import Path
from utils.relay_runtime import RelayRuntime, atomic_json, task_lock
root, mode = Path(sys.argv[1]), sys.argv[2]
with task_lock(root):
    runner = RelayRuntime(root)
    for index in range(30):
        output = root / f'cell-{index}.json'
        if output.exists():
            continue
        def send():
            if index == 5 and mode == 'interrupt':
                (root / 'ready').write_text('ready', encoding='utf-8')
                time.sleep(60)
            return {'value': index}, {}
        data = {'rows': [{'request_key': str(index), 'cn': f'Reward {index}'}], 'target_languages': ['EN']}
        result = runner.request('mock', 'translate', data, send)
        atomic_json(output, result)
    print(json.dumps({'requests': runner.requests}))
'''
    process = subprocess.Popen([sys.executable, '-c', code, str(tmp_path), 'interrupt'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / 'ready').exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.communicate()[1].decode())
            time.sleep(.02)
        assert (tmp_path / 'ready').exists()
        process.terminate()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
    completed = subprocess.run([sys.executable, '-c', code, str(tmp_path), 'resume'],
                               check=True, capture_output=True, text=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert json.loads(completed.stdout)['requests'] == 25
    assert len(list(tmp_path.glob('cell-*.json'))) == 30
    sends = [json.loads(line) for line in (tmp_path / 'relay_requests.jsonl').read_text(encoding='utf-8').splitlines()]
    assert sum(event['event'] == 'send' for event in sends) == 31  # Only the unsaved in-flight cell is resent.


def test_partial_translation_retries_only_failed_language_and_preserves_spacing(tmp_path):
    class Client:
        calls = []
        def translate_batch(self, rows, langs):
            self.calls.append(([row['request_key'] for row in rows], langs))
            return [{'request_key': row['request_key'], 'translations': {
                lang: (None if len(self.calls) == 1 and row['request_key'] == 'b' and lang == 'DE' else ' Reward ')
                for lang in langs}} for row in rows]
    client = Client()
    rows = [dict(request_key=key, cn='Reward') for key in ('a', 'b')]
    values, _ = _execute_batch(client, rows, ['EN', 'DE'], tmp_path, 3)
    assert client.calls == [(['a', 'b'], ['EN', 'DE']), (['b'], ['DE'])]
    assert values['a']['EN'] == ' Reward '
    again, reused = _execute_batch(client, rows, ['EN', 'DE'], tmp_path, 3)
    assert reused and again == values and len(client.calls) == 2


def test_success_is_retained_after_partial_exhaustion(tmp_path):
    class Client:
        def translate_batch(self, rows, langs):
            return [{'request_key': row['request_key'], 'translations': {lang: 'Reward' if row['request_key'] == 'a' else None for lang in langs}} for row in rows]
    rows = [dict(request_key=key, cn='Reward') for key in ('a', 'b')]
    with pytest.raises(IncompletePhase):
        _execute_batch(Client(), rows, ['EN'], tmp_path, 3)
    assert _cached_requests(tmp_path, rows, ['EN']) == {'a': {'EN': 'Reward'}}


def test_transport_and_validation_cannot_multiply_retries(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'base_url': 'https://example.invalid', 'model': 'mock', 'api_key': 'PRIVATE'}), encoding='utf-8')
    runner = runtime(tmp_path)
    client = OpenAICompatibleClient(config, runtime=runner)
    calls = []
    def response(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError('transient')
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': '{"rows":[]}'}}]}).encode())
    with patch('urllib.request.urlopen', side_effect=response), pytest.raises(IncompletePhase):
        _execute_batch(client, [{'request_key': 'a', 'cn': 'Reward'}], ['EN'], tmp_path, 3)
    assert len(calls) == 3
    assert 'PRIVATE' not in (tmp_path / 'relay_requests.jsonl').read_text(encoding='utf-8')


def test_truncation_splits_without_resetting_cell_budget(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'base_url': 'https://example.invalid', 'model': 'mock'}), encoding='utf-8')
    client = OpenAICompatibleClient(config, runtime=runtime(tmp_path))
    sent = []
    def response(request, **kwargs):
        data = json.loads(json.loads(request.data)['messages'][1]['content'])
        rows = data['rows']
        sent.append(len(rows))
        if len(rows) > 1:
            result = {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
        else:
            value = {'rows': [{'request_key': rows[0]['request_key'], 'translations': {'EN': 'Reward'}}]}
            result = {'choices': [{'message': {'content': json.dumps(value)}}]}
        return io.BytesIO(json.dumps(result).encode())
    rows = [{'request_key': str(i), 'cn': 'Reward'} for i in range(3)]
    with patch('urllib.request.urlopen', side_effect=response):
        values, _ = _execute_batch(client, rows, ['EN'], tmp_path, 3)
    assert len(values) == 3 and max(client.runtime.attempts.values()) == 3
    assert sent == [3, 1, 2, 1, 1]


class KeepClient:
    checkpoint_identity = 'keep-test'
    def translate_batch(self, rows, langs):
        raise AssertionError('review mode must not translate')
    def review_batch(self, rows, langs):
        return [dict(review_key=row['review_key'], lang=lang, status='KEEP', suggested=row['translations'][lang], reason='Meaning checked') for row in rows for lang in langs]
    def audit_batch(self, rows):
        return [dict(review_key=row['review_key'], lang=row['lang'], decision='ACCEPT', final=row['suggested'], reason='Source and target checked') for row in rows]


def make_review_source(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['ID', 'CN', 'EN', 'DE'])
    sheet.append(['1', 'Reward', 'Reward', 'Belohnung'])
    sheet.append(['2', None, 'leave unchanged', 'unveraendert'])
    sheet.append(['3', 'Reward', 'Prize', 'Preis'])
    workbook.save(path)
    workbook.close()


def test_review_only_end_to_end_and_source_drift(tmp_path):
    source = tmp_path / 'input.xlsx'
    make_review_source(source)
    client = KeepClient()
    kwargs = dict(inputs=[source], term_base=None, history_dirs=[], target_langs=['EN', 'DE'],
                  task_dir=tmp_path, relay_config=None, proofread_mode='full', task_mode='review',
                  translation_client=client, reviewer=client, auditor=client)
    result = run_pipeline(**kwargs)
    output = load_workbook(result.delivery_dir / source.name)
    assert output.active['C3'].value == 'leave unchanged'
    assert output.active['C2'].value == 'Reward'
    assert output.active['C4'].value == 'Prize'
    output.close()
    summary = json.loads((result.manifest.parent / 'deep_proofread/proofread_apply_summary.json').read_text(encoding='utf-8'))
    assert summary['reviewed_cells'] == 4
    assert result.hard_blockers == 0
    second = run_pipeline(**kwargs)
    assert second.delivery_dir == result.delivery_dir
    assert json.loads((result.manifest.parent / 'relay_progress.json').read_text(encoding='utf-8'))['requests'] == 0
    with source.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='source/terminology changed'):
        run_pipeline(**kwargs)


def test_keep_and_audit_preserve_boundary_whitespace():
    from utils.large_text_multilingual_proofread import _validate_suggestions, _validate_audit
    text = '\n  Reward  \n'
    row = {'review_key': 'a', 'cn': '\n  Reward  \n', 'translations': {'EN': text}}
    suggestion = _validate_suggestions([row], [{'review_key': 'a', 'lang': 'EN', 'status': 'KEEP', 'suggested': text}], ['EN'])[0]
    fix = {**suggestion, 'cn': row['cn'], 'current': text}
    decision = _validate_audit([fix], [{'review_key': 'a', 'lang': 'EN', 'decision': 'ACCEPT', 'final': text}])
    assert decision[('a', 'EN')]['final'] == text


def test_review_only_missing_target_is_reported_before_api(tmp_path):
    source = tmp_path / 'input.xlsx'
    make_review_source(source)
    workbook = load_workbook(source)
    workbook.active['D2'] = None
    workbook.save(source)
    workbook.close()
    client = KeepClient()
    with pytest.raises(ValueError, match='empty target cells'):
        run_pipeline(inputs=[source], term_base=None, history_dirs=[], target_langs=['EN', 'DE'],
                     task_dir=tmp_path, relay_config=None, proofread_mode='full', task_mode='review',
                     translation_client=client, reviewer=client, auditor=client)
    assert json.loads((tmp_path / '_work/large_text_multilingual/review_missing_cells.json').read_text(encoding='utf-8'))


def test_review_can_restore_missing_placeholder_against_source(tmp_path):
    source = tmp_path / 'input.xlsx'
    workbook = Workbook()
    workbook.active.append(['ID', 'CN', 'EN'])
    workbook.active.append(['1', 'Reward {0}', 'Reward'])
    workbook.save(source)
    workbook.close()
    class Repair(KeepClient):
        def review_batch(self, rows, langs):
            return [dict(review_key=row['review_key'], lang='EN', status='FIX', suggested='Reward {0}', reason='Restore missing placeholder') for row in rows]
    client = Repair()
    result = run_pipeline(inputs=[source], term_base=None, history_dirs=[], target_langs=['EN'],
                          task_dir=tmp_path, relay_config=None, proofread_mode='full', task_mode='review',
                          translation_client=client, reviewer=client, auditor=client)
    workbook = load_workbook(result.delivery_dir / source.name)
    assert workbook.active['C2'].value == 'Reward {0}'
    workbook.close()


def test_resume_restores_paths_and_concurrency(tmp_path):
    directory = tmp_path / '_work/large_text_multilingual'
    directory.mkdir(parents=True)
    (directory / 'run_config.json').write_text(json.dumps({'arguments': {
        'task_dir': str(tmp_path), 'inputs': [str(tmp_path / 'input.xlsx')], 'history_dirs': [],
        'relay_config': str(tmp_path / 'private.json'), 'api_concurrency': 4,
    }}), encoding='utf-8')
    with patch('utils.large_text_multilingual_pipeline.run_pipeline') as run:
        resume_pipeline(directory / 'large_text_multilingual_manifest.json', api_concurrency=5, retry_failed=True)
    assert run.call_args.kwargs['api_concurrency'] == 5
    assert run.call_args.kwargs['retry_failed'] is True
    assert isinstance(run.call_args.kwargs['inputs'][0], type(tmp_path))
