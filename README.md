# Nuki Events Home Assistant Integration

This repository provides a custom Home Assistant integration that listens for **Nuki decentral webhook events** and exposes recent smart lock activity in Home Assistant.

The integration is webhook-driven (no aggressive polling) and focuses on **who did what, how, and when** on your Nuki devices.

> [!IMPORTANT]
> This integration is not affiliated with or endorsed by Nuki.
> It is a completely independent project, backed up by the community, and based on official documentation and APIs.

> [!NOTE]
> **Disclaimer:** this project has been generated mainly by AI. Even though it has been reviewed and tested by a professional programmer, I feel like it's important to disclose this fact.
> 
---

## Features

- OAuth2 authentication against Nuki Web using **Home Assistant Application Credentials**
- Automatic registration of a **Nuki decentral webhook**
- Webhook handling for:
  - `DEVICE_LOGS` (lock / unlock actions, actor, timestamps)
  - `DEVICE_STATUS` (battery, door state, etc. – stored internally for future use)
- Creates sensors exposing the **last actor** and **last action** for each lock event
- Exposes rich, **human-readable attributes** (no numeric enums):
  - action (`lock`, `unlock`, `unlatch`, …)
  - trigger (`app`, `keypad`, `fingerprint`, …)
  - source (`nuki_app`, `bridge`, `keypad`, …)
  - device type (`smart_lock_3`, `smart_lock_4`, `opener`, …)
  - completion state (`success`, `low_battery`, …)
  - timestamp / date
  - event counter
- Handles different webhook payload shapes sent by Nuki
  (e.g. `smartlockId` nested under `smartlockLog`)

---

## Requirements

- Home Assistant **2026.1 or newer**
- A Nuki account with API access
- A Nuki OAuth application configured in Nuki Web
- A Home Assistant instance reachable from the internet (for webhook delivery)

---

## Setup

### 1. Install the integration

## HACS Installation

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Open the menu (three dots) → **Custom repositories**
4. Add this repository URL and select **Integration**
5. Install **Nuki Events**
6. Restart Home Assistant

## Manual Installation

1. Copy `custom_components/nuki_events` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant

---

### 2. Create Application Credentials

1. In Home Assistant, go to  
   **Settings → Devices & Services → Application credentials**
2. Add new credentials for **Nuki Events**
3. Enter your Nuki **Client ID** and **Client Secret**

> ⚠️ The redirect URL shown by Home Assistant must be added **exactly** to your OAuth app in Nuki Web.
> 2 options:
> - Through https://my.home-assistant.io/redirect/oauth
> - Direct to instance https://<my_domai>/auth/external/callback (make sure external routing & DNS are properly setup)

---

### 3. Add the integration

1. Go to **Settings → Devices & Services**
2. Add **Nuki Events**
3. Complete the OAuth2 authorization flow

After setup, the integration will:
- fetch the list of smartlocks once
- register a decentral webhook with Nuki
- create the sensor entity

---


## Entities

### Sensor: Smartlock Last Actor

A single sensor is created that represents the **last actor** who interacted with a Nuki device.

#### Sensor state
- The name of the actor (e.g. user name, keypad user, fingerprint, or device)

#### Attributes
- `action`: Lock action (`lock`, `unlock`, `unlatch`, …)
- `trigger`: How the action was triggered (`app`, `keypad`, `fingerprint`, …)
- `source`: Source system (`nuki_app`, `bridge`, `keypad`, …)
- `device_type`: Nuki device model (`smart_lock_3`, `smart_lock_4`, `opener`, …)
- `completion_state`: Result of the action (`success`, `low_battery`, …)
- `last_date`: ISO timestamp of the event (UTC)
- `event_counter`: Number of processed events for the lock

All enum values are translated into **human-readable strings**.  
Unknown future values will appear as `unknown(<value>)`.

### Sensor: Smartlock Last Action

A second sensor is created for each lock to represent the **last action** in a UI-friendly format.

#### Sensor state
- Last action in title case (e.g. `Unlock`, `Lock`, `Lock N Go With Unlatch`)

#### Attributes
- `actor`: Last actor linked to that action
- `trigger`: How the action was triggered (`app`, `keypad`, `fingerprint`, …)
- `source`: Source system (`nuki_app`, `bridge`, `keypad`, …)
- `completion_state`: Result of the action (`success`, `low_battery`, …)
- `date`: ISO timestamp of the event (UTC)
- `event_counter`: Number of processed events for the lock

---

## Webhooks

This integration uses **Nuki decentral webhooks**.

- Endpoint: managed automatically by Home Assistant
- Registration: performed during integration setup
- Transport: HTTPS
- No polling is required for log updates

If webhook registration fails, check:
- that your HA instance is reachable externally
- that your Nuki account/app has webhook permissions enabled

---

## Troubleshooting

### Integration authenticates but then asks to re-authenticate
- Verify Application Credentials are configured
- Ensure the redirect URL in Nuki Web matches Home Assistant exactly
- Check that your external Home Assistant URL is set correctly

### Webhooks arrive but the sensor does not update
- Only `DEVICE_LOGS` events update the actor/action attributes
- Check logs for payload normalization warnings
- Trigger a lock/unlock action to force a new log event

### Unknown enum values
- Nuki occasionally adds new enum values
- These will appear as `unknown(<number>)` until mappings are updated

---

## Notes

- This integration is intentionally webhook-driven to minimize API usage
- `DEVICE_STATUS` payloads are stored internally and may be exposed as attributes in future versions

---
