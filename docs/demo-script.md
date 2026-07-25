# Demo script (< 3 minutes)

1. **Hook (15s)** — “Dropping a column shouldn’t be a 2am incident. ContextGuard uses DataHub context to show blast radius before you merge.”
2. **Connect (20s)** — Open the app, enable Demo mode (or show live MCP connect).
3. **Select (20s)** — Pick `ecommerce.public.orders`.
4. **Analyze (40s)** — Enter `DROP COLUMN amount`. Show **Merge allowed: NO**, BREAKS count, certificate table — “this is not Impact Analysis.”
5. **Artifacts (45s)** — Consumer patches, compatibility SQL, certificate JSON hash. Mention `contextguard check` CI gate + Skill.
6. **Contrast (20s)** — Safe `status` type change → Merge allowed: YES.
7. **Close (20s)** — “Query proof → patches → merge gate → OSS skill. Reproduce from `examples/`.”

Record with public YouTube/Vimeo visibility. Keep UI zoom comfortable; avoid showing real tokens.
