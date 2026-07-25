# Example bundles

Generated with `contextguard gen-examples` using showcase-shaped fixture metadata (no live credentials).

| Bundle | Scenario |
|--------|----------|
| `breaking-drop-amount/` | Drop `amount` with critical Looker dashboard + dbt mart dependents |
| `safe-status-type-noop/` | Type change on `status` with no dependents (low risk) |

Each folder contains:

- `breakage_certificate.json` / `.md` — **merge gate input** (`cgcert/v1`)
- `consumer_patches.sql` — rewrites for BREAKS queries
- `impact_report.md`, `compatibility.sql`, `schema.yml`, `migration_checklist.md`, `owner_messages.txt`, `result.json`
