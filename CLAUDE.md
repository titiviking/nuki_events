# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .
```

Run a single test file: `pytest tests/test_coordinator.py`  
Run a single test: `pytest tests/test_coordinator.py::test_name`

## Architecture

This is a **Home Assistant custom integration** (`custom_components/nuki_events`) for Nuki smart locks. It is entirely **webhook-driven** — no polling after startup. All lock state changes arrive via Nuki's decentral webhooks.

### Module responsibilities

| File | Role |
|------|------|
| `__init__.py` | Entry point: OAuth token normalization, proactive token refresh, webhook lifecycle management, coordinator + webhook view setup |
| `config_flow.py` | OAuth2 config/reauth flow handler |
| `application_credentials.py` | Custom OAuth2 impl for Nuki's `client_secret_post` auth method; handles `expires_at` and refresh token preservation |
| `api.py` | Authenticated HTTP client wrapping Nuki Web API; maps OAuth2 errors to HA exceptions |
| `coordinator.py` | `DataUpdateCoordinator` (no poll interval); primes sensors from latest logs at startup, handles webhook payloads, manages per-lock auth name cache |
| `webhook.py` | `aiohttp` HTTP view at `/api/nuki_events/webhook/{token}`; token-based routing, HMAC-SHA256 signature verification |
| `sensor.py` | Three sensor entities per lock: `NukiLastActorSensor`, `NukiLastActionSensor`, `NukiWebhookDiagnosticSensor`; all extend `RestoreSensor` |
| `const.py` | Enums: `NUKI_ACTION`, `NUKI_TRIGGER`, `NUKI_DOORSTATE`, etc.; unknown values render as `unknown(<n>)` |

### Key flows

**Startup:**
1. Normalize token storage shape (legacy compat)
2. Force proactive OAuth2 token refresh (invalidates stale server-side tokens)
3. Validate cached webhook registration against live Nuki endpoints; reuse if valid, re-register if stale
4. `coordinator._async_update_data()`: fetch smartlock list, prime sensors from latest log entry, build auth name cache

**Webhook event:**
1. `NukiWebhookView` receives POST, verifies HMAC-SHA256 signature, routes to coordinator by token
2. `DEVICE_LOGS` → update `last_actor`/`last_action` sensor state + attributes
3. `DEVICE_AUTHS` → invalidate per-lock auth name cache (next event will rebuild it)
4. `DEVICE_STATUS` → stored (battery/door state, not yet exposed as sensors)

**Auth name resolution:**  
`authId` integers are resolved to human-readable names via `list_smartlock_auths()`. Cache is per-lock, rebuilt lazily when a `DEVICE_AUTHS` event arrives.

### Webhook secret management
Webhook registration stores a random token in `entry.data`. On valid reuse the same secret is kept (no re-registration churn). On stale/missing registration the old webhook is best-effort deleted, a new token is generated, and the new registration is persisted back to `entry.data`.

### HA integration constraints
- Minimum HA version: 2026.3 (see `manifest.json`)
- OAuth2 scopes: defined in `manifest.json`
- The integration is loaded by Home Assistant — there is no standalone runner


### Security audit scope

When performing security reviews, audit for the following by severity (Critical / High / Medium / Low):

1. OAuth2 token handling — storage, refresh lifecycle, expiry, leakage through logs or errors
2. Webhook endpoint security — authentication, token predictability, missing signature validation, replay attacks
3. Input validation — webhook payload sanitization, missing type checks, injection risks
4. Credential exposure — tokens, secrets, or keys leaking through logs, exceptions, or state attributes
5. HA-specific issues — unsafe use of hass.data, hardcoded secrets, sensitive data in entity state or attributes

For each finding provide: file and line number, description, and suggested fix.