# Relay validation follow-up, 2026-11-13

## Scope and version

The relay runtime, executor, proofreader, pipeline, and CLI matched commit
`f6305101da6a3db2429508344ea510cfba7f21ed` during this live task. The task also used a
private project client and local language-quality patches. This evidence validates
relay execution, coverage, checkpoint recovery, and the accepted delivery; it is not
a clean-commit benchmark of every quality rule. This follow-up changes documentation
only. Customer text, workbooks, credentials, request bodies, and local paths remain
outside the repository.

## Live workload

An anonymous glossary contained 824 source rows and four target languages, for
3,296 target cells. Translation used Chinese as the semantic source and English as
the naming reference. All target cells received line review and independent audit.

| Main pipeline stage | API requests | Observed stage duration |
| --- | ---: | ---: |
| Translation, including the initial smoke scope | 15 | 276.154 s |
| Full line review | 112 | 926.659 s |
| Independent audit | 112 | 894.137 s |

The configured and observed peak concurrency was four. The request journal recorded
no API failure or validation retry during these stages. The durations are model and
workload observations, excluding task preparation, the recovery interval, targeted
project terminology refinement, and final packaging. They do not predict the total
duration of a 40,000-row or long-prose job.

## Recovery and delivery evidence

The first deterministic QA pass blocked four display-bracket compatibility issues.
Only those four target values were repaired locally. Resume reused all 15 completed
translation batches and sent no new translation request. Full review and independent
audit then continued from the retained results.

Targeted project-level naming refinement followed the main pass. Final acceptance
confirmed all 3,296 target cells were populated, zero structural hard blockers, and
exact agreement between the accepted cache and workbook. The original source IDs,
Chinese text, classifications, and 820 existing English values were retained; four
English gaps were filled in their separately scoped pass.

Microsoft Excel opened the final glossary and QA workbook in normal load mode.
Every cell was compared with the expected values. The glossary retained 825 physical
rows including its header, one filtered table, and the original freeze panes. The
published current glossary and archived original were also read back successfully.

## Reuse boundary

This trial exercises real provider calls and checkpoint reuse at a larger scale than
the original 12-row smoke test. API outage handling, authentication stops, exhausted
retry budgets, and process termination remain covered by the existing stability
tests; this trial did not induce those failures again. A large long-text task still
starts with a representative scope and estimates translation, review, and audit
throughput separately. Keep the shared concurrency limit at five or below.

The 17 stability tests were rerun successfully in a clean worktree at the recorded
source revision using `python -m pytest tests/test_relay_runtime.py -q` before this
documentation update was committed.

Task-specific naming decisions and credentials stay in private project files. The
default execution contract remains [RELAY_STABLE_EXECUTION.md](RELAY_STABLE_EXECUTION.md).
