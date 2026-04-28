# English Sample QA Output

This is a compact example of the report a game localization reviewer should expect after checking an Excel language pack.

| ID | Source | Translation | Finding | Suggested action |
| --- | --- | --- | --- | --- |
| 1001 | Start Battle | Start Battle | OK | Keep |
| 1002 | {0} Gold | Gold | variable_missing | Restore `{0}` |
| 1003 | `<color>Epic</color>` | `<color>Epic` | ui_tag_unclosed | Restore closing tag |
| 1004 | Registration | Registration | term_review_needed | Check whether UI should use `Sign Up` |
| 1005 | Claim Reward | Claim Your Exclusive Limited-Time Login Reward Now | ui_length_overflow | Shorten for compact UI |

## Minimal command

```bash
python process_language.py --input sample-language.xlsx --lang en
```

The sample CSV is documentation-only. Use `sample-language.xlsx` or your own Excel language pack for the runnable command.
