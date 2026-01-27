"""Tests for OAuth flow configuration."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_oauth() -> None:
    manifest_path = ROOT / "custom_components" / "nuki_events" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["config_flow"] is True
    oauth = manifest["oauth2"]
    assert oauth["authorization_url"].startswith("https://")
    assert oauth["token_url"].startswith("https://")
    assert "webhook.write" in oauth["scopes"]


def test_config_flow_uses_oauth_handler() -> None:
    flow_path = ROOT / "custom_components" / "nuki_events" / "config_flow.py"
    content = flow_path.read_text()
    assert "OAuth2FlowHandler" in content
