# Accessibility notes (Streamlit judge UI)

Verified manually against the four-step flow:

- Each control has a visible label (`text_input`, `selectbox`, `text_area`, `checkbox`, `button`).
- Primary actions use Streamlit's `type="primary"` for clear focus hierarchy.
- Progress indicator announces the current step text.
- Risk / unknowns use Streamlit warning/error/success regions rather than color alone.
- Password fields for secrets; exports never include tokens or raw MCP payloads.
- Keyboard: Streamlit native tab order covers inputs → actions; download button is reachable after analysis.

Theme contrast: dark text `#1C1917` on `#F7F4EF` / `#E8E2D8` backgrounds; primary `#0F6E56`.
