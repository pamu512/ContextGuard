# Migration checklist

1. Review Breakage Certificate — merge allowed only if BREAKS == 0.
2. Confirm risk score (91) with owners.
3. Apply consumer patches for each BREAKS query (see consumer_patches.sql).
4. Open PR with compatibility SQL + dbt tests from this package.
5. Notify downstream owners (messages below).
6. Deploy compatibility view / dual-write period.
7. Migrate consumers, then remove compatibility shim.
8. Re-run ContextGuard; certificate must allow merge before cutover.