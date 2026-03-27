# Nuki Events — Home Assistant Integration

A custom Home Assistant integration that receives **Nuki decentral webhook events** and exposes smart lock activity as sensors. Fully webhook-driven — no polling, no delays.

> [!IMPORTANT]
> This integration is not affiliated with or endorsed by Nuki.
> It is an independent community project based on official Nuki API documentation.

> [!NOTE]
> **Disclaimer:** this project has been developed with AI assistance and reviewed by a professional programmer.

---

## Features

- **OAuth2 authentication** via Home Assistant Application Credentials
- **Webhook-driven updates** — sensors update instantly when your lock is used
- **Smart webhook lifecycle management** — the registration is validated on every startup and reused when still valid; re-registration only happens when genuinely needed, preserving the same secret across restarts
- **State restoration** — sensors restore their last known value immediately after a restart, before the first webhook arrives
- **Webhook diagnostic sensor** — exposes the health of the webhook registration in real time, including URL match, secret validity, and all live endpoints registered on the Nuki server
- **Human-readable attributes** — all Nuki enum values (action, trigger, source, device type, completion state) are translated to readable strings
- **Auth name resolution** — actor names are resolved from the Nuki auth list at startup so sensors show real names rather than raw IDs
- **Minimum HA version enforced** — requires Home Assistant 2026.3 or newer

---

## Sensors

Two sensors are created per smartlock, plus one integration-level diagnostic sensor.

### Last Actor (`sensor.<lock_name>_last_actor`)

Reports who most recently interacted with the lock.

| | |
|---|---|
| **State** | Name of the actor (e.g. `Alice`, `Keypad user`, `System`) |
| `action` | Lock action: `lock`, `unlock`, `unlatch`, `lock_n_go`, … |
| `trigger` | How triggered: `app`, `web`, `button`, `keypad`, `accessory`, … |
| `source` | Source system: `nuki_app`, `bridge`, `keypad`, `fob`, … |
| `deviceType` | Device model: `smart_lock_3`, `smart_lock_4`, `opener`, … |
| `completion_state` | Result: `success`, `motor_blocked`, `canceled`, … |
| `date` | ISO 8601 timestamp of the event (UTC) |
| `authId` | Raw authorization ID (not recorded in history) |
| `event_counter` | Number of events processed for this lock (not recorded in history) |

### Last Action (`sensor.<lock_name>_last_action`)

Reports the most recent lock action in a UI-friendly format.

| | |
|---|---|
| **State** | Action in title case: `Lock`, `Unlock`, `Lock N Go With Unlatch`, … |
| `actor` | Name of the actor who triggered the action |
| `trigger` | How triggered: `app`, `web`, `button`, `keypad`, `accessory`, … |
| `source` | Source system: `nuki_app`, `bridge`, `keypad`, `fob`, … |
| `completion_state` | Result: `success`, `motor_blocked`, `canceled`, … |
| `date` | ISO 8601 timestamp of the event (UTC) |
| `event_counter` | Number of events processed for this lock (not recorded in history) |

### Webhook Diagnostic (`sensor.nuki_events_integration_webhook_diagnostic`)

An integration-level diagnostic sensor (visible under the **Nuki Events Integration** device card) that reports the health of the webhook registration.

| | |
|---|---|
| **State** | `matched`, `unmatched`, or `error` |
| `registered_id` | Webhook ID cached in HA entry data |
| `registered_url` | URL this integration expects to be registered on Nuki |
| `registered_features` | Features subscribed on the matching live endpoint |
| `live_endpoints` | All endpoints currently registered on the Nuki server |
| `url_match` | `true` if the expected URL is found among live endpoints |
| `secret_match` | `true` if the cached webhook ID matches the live endpoint ID (proxy for correct secret — Nuki does not expose secrets via API) |
| `last_checked` | ISO 8601 timestamp of the last diagnostic run |
| `error` | Error message if the API call failed |

Use this sensor to diagnose signature verification failures or missing webhook deliveries without digging through logs.

---

## Requirements

- Home Assistant **2026.3 or newer**
- A Nuki account with **Advanced API** access enabled
- A Nuki OAuth application (Client ID + Client Secret) configured in Nuki Web
- A Home Assistant instance **reachable from the internet** (required for webhook delivery)

---

## Installation

### HACS (recommended)

1. Open HACS → **Integrations**
2. Three-dot menu → **Custom repositories**
3. Add this repository URL, select **Integration**
4. Install **Nuki Events** and restart Home Assistant

### Manual

1. Copy `custom_components/nuki_events` into your HA `custom_components` directory
2. Restart Home Assistant

---

## Setup

### 1. Create Application Credentials

1. In Nuki Web (**Menu → API**), request **Advanced API Integration** access if you haven't already
2. Once approved, note your **Client ID** and **Client Secret**
3. In Home Assistant: **Settings → Devices & Services → Application Credentials**
4. Add credentials for **Nuki Events**, entering your Client ID and Secret

> ⚠️ The redirect URL shown by Home Assistant must be added **exactly** to your OAuth application in Nuki Web. Two options:
> - `https://my.home-assistant.io/redirect/oauth`
> - `https://<your-domain>/auth/external/callback` (requires correct external URL and DNS)

### 2. Add the integration

1. **Settings → Devices & Services → Add Integration → Nuki Events**
2. Complete the OAuth2 authorization flow in the browser

On first setup the integration will:
- Fetch your smartlock list from the Nuki API
- Prime sensors with the most recent log entry per lock
- Register a decentral webhook with Nuki
- Create all sensor entities

On subsequent restarts:
- Sensors restore their last known state immediately from HA storage
- The existing webhook registration is validated and reused if still valid
- Re-registration only occurs if the cached registration is no longer found on the Nuki server

---

## Webhook Handling

This integration uses **Nuki decentral webhooks** — Nuki posts events directly to your HA instance as they happen.

**Subscribed features:**
- `DEVICE_LOGS` — lock/unlock actions, actor, timestamps → updates Last Actor and Last Action sensors
- `DEVICE_STATUS` — battery, door state, server state → stored internally
- `DEVICE_AUTHS` — authorization changes → invalidates the actor name cache so renames are reflected on next restart

**Signature verification:** every incoming webhook is verified against an HMAC-SHA256 signature using the secret obtained at registration. Requests with an invalid or missing signature are rejected with HTTP 401.

**Webhook lifecycle:**
- Registration is kept alive across HA restarts — the same endpoint and secret are reused as long as they are still valid
- If the registration is found to be stale (wrong URL or missing from the Nuki server), the old endpoint is deregistered and a new one is registered automatically
- The **Webhook Diagnostic** sensor reflects the outcome of this check after every startup

---

## Troubleshooting

### Sensors show `unknown` after restart
- This is normal on the very first boot (no prior state to restore)
- On subsequent restarts, state is restored from HA storage within milliseconds
- If sensors remain `unknown` after a lock/unlock event, check the **Webhook Diagnostic** sensor

### Webhook Diagnostic shows `unmatched`
- The cached webhook registration is no longer valid on the Nuki server
- Reload the integration — it will automatically deregister the stale endpoint and register a fresh one
- Verify your HA external URL hasn't changed (Settings → System → Network)

### Signature verification failures in logs
- The warning includes the first 8 characters of both the received and expected signatures, and the length of the stored secret
- A secret length of 0 suggests the credentials were never properly saved — reload the integration
- After deploying 2.5.3 or newer, one reload is sufficient to establish fresh credentials

### Sensors update but actor shows a numeric ID instead of a name
- The actor name cache is built from `GET /smartlock/{id}/auth` at startup
- If the auth list call fails (e.g. network issue), the raw `authId` is used as fallback
- Reloading the integration rebuilds the cache

### Unknown enum values appear as `unknown(<number>)`
- Nuki occasionally introduces new enum values
- These will display as `unknown(<number>)` until the next release adds the mapping

### Integration asks to re-authenticate unexpectedly
- Verify Application Credentials are still configured under Settings → Devices & Services → Application Credentials
- Ensure the redirect URL in Nuki Web matches exactly what HA displays
- Check that your external HA URL is configured correctly under Settings → System → Network

---

## Notes

- The integration makes no polling API calls during normal operation — all state updates arrive via webhook
- `DEVICE_STATUS` payloads are captured and may be exposed as additional attributes in a future release
- The `event_counter` and `authId` attributes are excluded from the HA long-term recorder database to avoid unnecessary database growth