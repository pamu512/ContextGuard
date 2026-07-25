# Upstream contribution note

This skill is packaged for contribution to [`datahub-project/datahub-skills`](https://github.com/datahub-project/datahub-skills).

## Suggested PR title

`feat: add contextguard-breakage-cert skill (query-aware schema merge gate)`

## Suggested PR body

```markdown
## Summary
Adds a skill that issues Query-Aware Breakage Certificates using DataHub MCP
(`get_dataset_queries` + lineage/schema). Goes beyond Impact Analysis by classifying
known queries as BREAKS/SAFE/UNKNOWN and deciding merge_allowed.

## Test plan
- [ ] Load skill in Claude Code / Cursor with DataHub MCP connected
- [ ] Propose `DROP COLUMN amount` on a showcase dataset with known queries
- [ ] Confirm BREAKS verdict + consumer patch
- [ ] Confirm write-back only after explicit confirmation
```

Copy `SKILL.md` into the upstream skills registry when opening the PR.
