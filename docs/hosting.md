# Hosting ContextGuard

## Streamlit Community Cloud (recommended durable demo)

1. Open https://share.streamlit.io and sign in with GitHub
2. **New app** → `pamu512/ContextGuard` → branch `main` → main file `app.py`
3. Leave secrets empty → **Demo mode auto-enables**
4. Paste the `*.streamlit.app` URL into Devpost **Try it out**

Optional secrets (live DataHub):

```toml
DATAHUB_MCP_URL = "https://<tenant>.acryl.io/integrations/ai/mcp"
DATAHUB_TOKEN = "..."
GOOGLE_API_KEY = "..."
CONTEXTGUARD_ALLOW_WRITEBACK = "false"
CONTEXTGUARD_DEMO = "false"
```

## Docker

```bash
docker compose up --build
# http://localhost:8501
```

## Quick public tunnel (ephemeral)

```bash
CONTEXTGUARD_DEMO=true streamlit run app.py --server.port 8501 &
cloudflared tunnel --url http://localhost:8501
```
