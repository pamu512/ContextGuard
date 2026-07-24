# Migration checklist

1. Confirm risk score (60) with owners.
2. Open PR with compatibility SQL + dbt tests from this package.
3. Notify downstream owners (messages below).
4. Deploy compatibility view / dual-write period.
5. Migrate consumers, then remove compatibility shim.
6. Re-run ContextGuard analysis after cutover.