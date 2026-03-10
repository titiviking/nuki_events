## Description

<!-- What does this PR change and why? -->

---

## Type of change

- [ ] Bug fix
- [ ] New feature / enhancement
- [ ] Refactor / code quality
- [ ] Documentation / strings
- [ ] Dependency / manifest update

---

## Checklist

### Nuki API
- [ ] Any new or modified API calls have been verified against the [Nuki Web API docs](https://api.nuki.io)
- [ ] OAuth2 scopes required by new endpoints are declared in `manifest.json` and `const.py DEFAULT_SCOPES`
- [ ] Webhook feature strings match the official spec exactly (`DEVICE_STATUS`, `DEVICE_LOGS`, `DEVICE_AUTHS`, etc.)

### Home Assistant integration patterns
- [ ] New entities have `unique_id` and `device_info` set
- [ ] `_attr_has_entity_name = True` sensors use a suffix-only `_attr_name` (HA prepends the device name)
- [ ] Coordinator state is deep-copied before being passed to `async_set_updated_data`
- [ ] Auth failures raise `ConfigEntryAuthFailed` (not swallowed) so HA can trigger reauth
- [ ] Any new strings are added to both `strings.json` and `translations/en.json`

### Webhook behaviour
- [ ] Signature verification (`X-Nuki-Signature-SHA256`) is not bypassed
- [ ] Unhandled webhook features are logged at `DEBUG` and return early (no spurious state push)
- [ ] `async_unload_entry` cleans up any server-side registrations made during setup

### Testing
- [ ] Existing tests still pass (`pytest tests/`)
- [ ] Sensors show a populated value immediately after integration reload (not `unknown`)
- [ ] Behaviour verified with at least one real Nuki webhook payload if webhook handling changed