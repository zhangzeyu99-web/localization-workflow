# Stable relay translation and proofreading

## Execution contract

The V2 runner uses the relay API for translation, line review, and independent audit.
It never launches Codex subagents or silently switches to subscription-backed review.
Codex orchestration and debugging still use normal interactive quota; the relay bills
its own requests. Keep customer workbooks, credentials, and process artifacts private.

- `--api-concurrency` defaults to 4 and accepts only 1 through 5. All languages and
  API roles share this limit. Existing worker options cannot increase the limit.
- At most twice the worker count is submitted to the local executor. Successful
  requests have no fixed delay or extra review round. Review and audit use one
  target language per batch, with row and request/output size limits.
- Initial translation, review, and audit save accepted cells immediately. Only
  unresolved cells are retried, with validation feedback. Source/context/model/policy
  changes invalidate affected caches; changing batch size does not discard success.
- Each semantic input cell and stage has at most three actual requests. Attempts
  survive restart and splitting; transport and validation retries cannot multiply.
- Timeout/5xx use shared exponential backoff with jitter; 429 honors Retry-After and
  reduces concurrency. Three consecutive service failures trigger a shared cooldown.
  Authentication, exhausted credit, or invalid settings stop dispatch immediately.
  A continuous 15-minute outage exits with checkpoints, rather than looping forever.
- Only explicit request/context limits or output truncation split batches. A normal
  network failure does not split. Bad cells do not cancel healthy batches in the same
  phase; unresolved cells still block completion and delivery.
- One task lock covers preparation through delivery. Normal interruption stops new
  submissions and waits for in-flight calls to save results. Hard process termination
  can lose an unsaved response; a relay may have billed that response already.

## Commands

Use project-local source copies and the existing V2 options for terms, languages,
source mode, and delivery location. These examples show only the added controls.

```powershell
python scripts/run_large_text_multilingual_runner.py run `
  --input <source.xlsx> --target-langs EN,DE,FR,ES --task-dir <project-batch> `
  --relay-config <private-config.json> --proofread-mode full --api-concurrency 5

python scripts/run_large_text_multilingual_runner.py run `
  --input <existing-translations.xlsx> --target-langs EN,DE,FR,ES `
  --task-dir <review-batch> --relay-config <private-config.json> --task-mode review

python scripts/run_large_text_multilingual_runner.py resume --manifest <manifest.json>
python scripts/run_large_text_multilingual_runner.py status --manifest <manifest.json>
```

Optional `--review-relay-config` and `--audit-relay-config` select separate models or
providers, while retaining the same total concurrency limit. Otherwise both reuse
the configured relay model with separate review/audit requests.

Review mode does not translate or clear existing targets. It defaults to full review
and audit, preserves empty-source rows, and reports missing target cells before any
API call. Fill those gaps as a separately authorized translation scope. Existing
translation mode retains its empty-target requirement. Broken source/code structures
and unresolved semantics remain visible blockers, not automatic Codex fallbacks.

Use `resume --retry-failed` only after addressing the reported problem. It resets
exhausted budgets, not accepted results. Source/terminology changes require a new task
directory; old artifacts are preserved. A completed task is read-verified rather than
translated/exported again. `run_config.json` stores paths/options, never API secrets.

## Quality and observation

Source, glossary, target-language policy (`native-baseline-v1`), explicit English
reference, and approved concise wording remain binding. KEEP and FIX both receive
independent API audit. Structured text is rebuilt by the program; the audit also
receives complete readable proposed text to catch clause joins and omissions without
handing code ownership to the model. Whole-cell structural QA and actual XLSX readback
remain required. No sampled mode is presented as full review.

`relay_progress.json` is refreshed on dispatch, fatal stop and return to idle; other
updates are throttled to 30 seconds. It includes PID, timestamp and stop reason. The append-only
request journal records attempts, stages, failures, latency, and returned usage.
Missing usage is unknown, not zero. Blind dialogue readings are cached independently
so a later audit retry does not repeat a successful blind-reading call. Failure lists
stay in `_work`; they are not successful delivery files.

For conditional ETAs, mandatory first-turn/appointment reporting, independent queue
selection and pre-export surface checks, follow
[RELAY_EFFICIENCY_AND_REPORTING.md](RELAY_EFFICIENCY_AND_REPORTING.md).
Pipeline completion alone is not project publication or native Excel acceptance.

## Stability and performance acceptance

Run `tests/test_relay_runtime.py` plus the affected V2 tests. The offline benchmark
`scripts/benchmark_relay_runtime.py --output-dir <private-validation-dir>` defaults to
40,000 source rows and four languages. It compares old eager submission with bounded
submission using identical simulated calls and batch checkpoints. It does not measure
model quality, real provider throughput, or full workbook pipeline duration.

The validated five-worker run made 11,339 requests in both cases: 18.770 versus 22.250
seconds with a 5 ms simulated API latency. Added local overhead was 3.480 seconds in
total, about 0.307 ms per request. All 11,339 checkpoints were readable; peak API
concurrency was five. These numbers must not be extrapolated as actual model speed.

A live anonymous 12-row/four-language full run completed in 84.450 seconds, with 11
requests (including two validation retries), zero hard blockers, native Excel readback
of all 48 target cells, and zero new API requests on resume. A real 40,000-row workload
still starts with about 300 representative rows; retain these results and measure
stage throughput before estimating total duration. Do not raise concurrency above five.

The subsequent live 824-row/four-language trial, including full review, independent
audit, checkpoint recovery, and native Excel acceptance, is recorded in
[RELAY_VALIDATION_20261113.md](RELAY_VALIDATION_20261113.md). Its stage durations and
version boundaries are explicit; customer data and credentials remain private.
