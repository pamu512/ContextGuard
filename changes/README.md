# Change requests

| Folder | Purpose |
|--------|---------|
| `demo/` | Sample change files for docs & local demos (not CI-gated) |
| `active/` | Put real PR change requests here — the merge gate certifies these |

```bash
# Demo (local)
contextguard certify changes/demo/drop-amount.json --out-dir artifacts/drop --fail-on-breakage
contextguard certify changes/demo/safe-status-noop.json --out-dir artifacts/safe

# Real PR workflow: add changes/active/my-change.json then open a PR
```
