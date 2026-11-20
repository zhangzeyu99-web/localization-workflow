from datetime import datetime, timezone
import unittest

from utils.large_text_multilingual_runner import workflow_status
from utils.workflow_progress import delivery_status, queue_status, update_progress


class WorkflowProgressTests(unittest.TestCase):
    def manifest(self):
        return {'status': 'api_translate_running',
                'critical_path': ['api_translate', 'subagent_review', 'controller_merge', 'write_outputs'],
                'phase_status': {'api_translate': 'running', 'subagent_review': 'pending',
                                 'controller_merge': 'pending', 'write_outputs': 'pending'},
                'preflight': {'estimated_target_cells': 1000}}

    def test_reuse_is_not_fresh_throughput_and_first_batch_produces_conditional_eta(self):
        manifest = self.manifest()
        update_progress(manifest, 'api_translate', total=1000, accepted=900, reused=900, seconds=1)
        self.assertIsNone(delivery_status(manifest)['estimated_completion_at'])
        update_progress(manifest, 'api_translate', total=1000, accepted=920, reused=900, seconds=60)
        result = delivery_status(manifest)
        self.assertGreater(result['estimated_active_remaining_seconds'][0], 9000)
        self.assertIsNotNone(result['estimated_completion_at'])
        self.assertTrue(result['assumptions'])

    def test_failure_and_unknown_wait_are_not_reported_as_finished(self):
        manifest = self.manifest()
        manifest['phase_status']['api_translate'] = 'failed'
        manifest['phase_events'] = [{'phase': 'api_translate', 'event': 'failed', 'error': 'quota exhausted'}]
        manifest['reporting'] = {'next_report_at': '2026-11-16T01:00:00+08:00'}
        result = delivery_status(manifest, now=datetime(2026, 11, 16, tzinfo=timezone.utc))
        self.assertTrue(result['report_required'])
        self.assertTrue(result['report_overdue'])
        self.assertEqual(result['report_alerts'], ['blocked', 'checkpoint_due'])
        self.assertEqual(result['blockers'][0]['reason'], 'quota exhausted')
        self.assertIsNone(result['estimated_completion_at'])
        self.assertEqual(workflow_status(manifest)['next_phase'], 'api_translate')

    def test_local_acceptance_is_included_and_completion_needs_all_phases(self):
        manifest = self.manifest()
        for phase in ('api_translate', 'subagent_review', 'controller_merge'):
            manifest['phase_status'][phase] = 'done'
        result = delivery_status(manifest)
        self.assertFalse(result['complete'])
        self.assertEqual(result['estimated_active_remaining_seconds'], [120, 360])
        manifest['phase_status']['write_outputs'] = 'done'
        manifest['status'] = 'complete'
        self.assertEqual(delivery_status(manifest)['estimated_active_remaining_seconds'], [0, 0])

    def test_resume_does_not_replace_large_sample_with_small_retry(self):
        manifest = self.manifest()
        update_progress(manifest, 'api_translate', total=1000, accepted=800, reused=0, seconds=800)
        update_progress(manifest, 'api_translate', total=1000, accepted=805, reused=800, seconds=100)
        result = delivery_status(manifest)
        self.assertEqual(result['accepted_progress']['api_translate']['accepted_cells'], 805)
        self.assertEqual(result['estimated_active_remaining_seconds'][0], 3267)
        update_progress(manifest, 'api_translate', total=1000, accepted=805, reused=805, seconds=3)
        self.assertEqual(delivery_status(manifest)['estimated_active_remaining_seconds'][0], 3267)
        update_progress(manifest, 'api_translate', total=1000, accepted=905, reused=805, seconds=300)
        self.assertGreater(delivery_status(manifest)['estimated_active_remaining_seconds'][0], 9000)

    def test_warns_before_checkpoint_if_forecast_outgrows_last_promise(self):
        manifest = self.manifest()
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        manifest['reporting'] = {
            'next_report_at': '2026-11-16T12:30:00+00:00',
            'promised_by': '2026-11-16T12:20:00+00:00',
        }
        update_progress(manifest, 'api_translate', total=1000, accepted=800, reused=0, seconds=800)
        result = delivery_status(manifest, now=now)
        self.assertTrue(result['report_now'])
        self.assertFalse(result['report_overdue'])
        self.assertEqual(result['report_alerts'], ['forecast_exceeds_promise'])
        self.assertIn('promised_time_reached', delivery_status(manifest, now=now.replace(minute=20))['report_alerts'])

    def test_pending_source_does_not_block_unrelated_batch_but_running_owner_does(self):
        queue = {'items': [{'id': 'body', 'state': 'blocked', 'pending_source_ids': ['78039']},
                           {'id': 'mail', 'state': 'pending'},
                           {'id': 'dependent', 'state': 'pending', 'depends_on': ['body']},
                           {'id': 'accepted', 'state': 'complete'}]}
        self.assertEqual(queue_status(queue)['next_runnable'], 'mail')
        queue['items'][1]['state'] = 'running'
        self.assertIsNone(queue_status(queue)['next_runnable'])
        self.assertTrue(queue_status(queue)['requires_live_process_check'])

    def test_model_complete_is_local_acceptance_not_an_api_restart(self):
        queue = {'items': [{'id': 'body', 'state': 'awaiting_visual_acceptance'},
                           {'id': 'mail', 'state': 'pending'}]}
        self.assertEqual(queue_status(queue)['local_acceptance_items'], ['body'])
        self.assertEqual(queue_status(queue)['next_runnable'], 'mail')
        queue['state'] = 'paused'
        self.assertIsNone(queue_status(queue)['next_runnable'])

    def test_no_failed_event_and_pipeline_scope_do_not_claim_formal_delivery(self):
        manifest = self.manifest()
        manifest['phase_status']['api_translate'] = 'failed'
        self.assertTrue(delivery_status(manifest)['blockers'])
        manifest['phase_status'] = {phase: 'done' for phase in manifest['critical_path']}
        self.assertEqual(delivery_status(manifest)['current_phase'], 'awaiting_completion_record')
        manifest['status'] = 'complete'
        result = delivery_status(manifest)
        self.assertEqual(result['completion_scope'], 'native_pipeline_only')
        self.assertIn('native_excel_acceptance', result['formal_delivery_requires'])

    def test_report_checkpoint_cli_persists_only_explicit_future_timestamp(self):
        import contextlib
        import io
        import json
        from pathlib import Path
        import tempfile
        from datetime import timedelta
        from utils.large_text_multilingual_runner import main

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'
            manifest = {**self.manifest(), 'manifest_path': str(path)}
            path.write_text(json.dumps(manifest), encoding='utf-8')
            deadline = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            args = ['record-report', '--manifest', str(path), '--reason', 'actual report delivered',
                    '--next-report-at', deadline]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args + ['--promised-by', deadline]), 0)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), manifest)
            saved = json.loads(path.with_suffix('.reporting.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['last_report_reason'], 'actual report delivered')
            # A concurrent runner rewrites only its manifest from its own in-memory state.
            manifest['updated_at'] = 'worker tick'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['status', '--manifest', str(path)]), 0)
            self.assertIsNotNone(json.loads(output.getvalue())['delivery']['promised_by'])
            self.assertFalse(json.loads(output.getvalue())['delivery']['report_overdue'])
            with self.assertRaisesRegex(ValueError, 'explicit timezone'):
                main(args[:-1] + ['2026-11-16T00:00:00'])


if __name__ == '__main__':
    unittest.main()
