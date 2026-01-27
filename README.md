# Nuki Events Home Assistant Integration

This repository provides a custom Home Assistant integration that listens for Nuki Web webhook events and exposes the most recent smartlock actor as a sensor.

## Features

- OAuth2 authentication against Nuki Web.
- Registers a webhook endpoint with Nuki Web for device log events.
- Exposes `sensor.smartlock_last_actor` with attributes for timestamp, smartlock name, and source.

## Setup

1. Copy `custom_components/nuki_events` into your Home Assistant `custom_components` directory.
2. In Home Assistant, add the **Nuki Events** integration.
3. Complete the OAuth2 flow to authorize access to your Nuki account.
4. Ensure your Home Assistant instance is reachable by Nuki Web for webhook delivery.

## Sensor Attributes

The `sensor.smartlock_last_actor` entity exposes:

- `timestamp`: The event timestamp reported by Nuki.
- `smartlock_name`: The name of the smartlock.
- `source`: The unlock source (fingerprint, keypad, etc.).

## Testing

Run the lightweight checks included in this repo:

```bash
python -m pytest
```
