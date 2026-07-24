"""Foundation smoke tests — package import and settings validation."""

from contextguard import __version__
from contextguard.config import Settings


def test_version_present():
    assert __version__


def test_settings_require_runtime_missing():
    settings = Settings(
        GOOGLE_API_KEY="",
        DATAHUB_MCP_URL="",
        DATAHUB_TOKEN="",
    )
    try:
        settings.require_datahub()
        raised = False
    except ValueError as exc:
        raised = True
        assert "DATAHUB_MCP_URL" in str(exc)
    assert raised


def test_settings_require_runtime_ok():
    settings = Settings(
        GOOGLE_API_KEY="k",
        DATAHUB_MCP_URL="https://example.acryl.io/integrations/ai/mcp",
        DATAHUB_TOKEN="t",
    )
    settings.require_datahub()
    settings.require_runtime()
