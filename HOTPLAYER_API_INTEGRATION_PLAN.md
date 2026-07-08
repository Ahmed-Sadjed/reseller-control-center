# HotPlayer API Integration Plan

## Overview

Extend the platform to support HotPlayer's device management endpoints beyond activation:
**Check Device**, **Add Playlists**, and **Delete Playlists**. These are post-purchase
operations — resellers need to manage their activated devices (MAC addresses) after buying.

---

## 1. Architecture Design

### 1.1 Base Adapter Extension

Add optional lifecycle methods to `BaseProviderAdapter` with default
`NotImplementedError` implementations. This keeps the contract clean: views call
methods uniformly, unsupported providers fail clearly.

**`backend/api/providers/base.py`** — new methods on `BaseProviderAdapter`:

```python
def check_device(self, mac: str) -> dict:
    """Query provider for device status/expiry/details."""
    raise NotImplementedError(f"Provider '{type(self).__name__}' does not support check_device")

def add_playlists(self, mac: str, playlists: list[dict]) -> dict:
    """Attach external playlists (M3U URLs / Xtream Codes) to a device MAC."""
    raise NotImplementedError(f"Provider '{type(self).__name__}' does not support add_playlists")

def delete_playlists(self, mac: str) -> dict:
    """Remove all playlists from a device MAC."""
    raise NotImplementedError(f"Provider '{type(self).__name__}' does not support delete_playlists")
```

### 1.2 HotPlayerAdapter Implementation

All three map directly to the existing `self.api_url` base with the same `ApiKey` header:

| Method | HTTP | Path | Notes |
|--------|------|------|-------|
| `check_device(mac)` | `GET` | `/check-device/{mac}` | returns device info |
| `add_playlists(mac, playlists)` | `POST` | `/add-playlists/{mac}` | body: `{playlists: [...]}` |
| `delete_playlists(mac)` | `DELETE` | `/delete-playlists/{mac}` | removes all playlists |

Error handling reuses the same pattern (timeout, connection, HTTP, JSON parse,
`status == 'error'`).

### 1.3 MockProviderAdapter Implementation

Add mock implementations that return fabricated data. This allows full frontend
development without real API calls.

### 1.4 CMSOnlyAdapter / Neo4k

These do **not** support device management. The base `NotImplementedError` will
cause the API to return `400 Bad Request` with a clear message like
*"This provider does not support device management."*

---

## 2. Data Model

**No new database models are needed.**

The `Credential` model already stores the identity data:

| Credential Field | HotPlayer Value |
|---|---|
| `external_username` | MAC address (e.g. `00:1A:79:AB:CD:EF`) |
| `expires_at` | Subscription expiry |
| `is_revoked` | Whether the line is active/blocked |

The credential's `order.product.provider` chain gives us the `Provider` instance
needed to obtain the adapter.

---

## 3. REST API Endpoints

All new endpoints are scoped to credentials owned by the authenticated user.

### 3.1 Check Device

```
GET /api/credentials/{credential_id}/device/
```

**Response 200:**
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "active",
    "expires_at": "2026-07-08T00:00:00Z",
    "plan": "MONTHS_6",
    "playlist_count": 2,
    "provider_response": { ... }
}
```

**Response 400 (unsupported provider, or HotPlayer returns error):**
```json
{ "error": "Provider 'CMSOnlyAdapter' does not support check_device" }
```

### 3.2 Add Playlists

```
POST /api/credentials/{credential_id}/device/playlists/
```

**Request:**
```json
{
    "playlists": [
        { "url": "http://example.com/get.php?username=foo&password=bar", "name": "My Playlist" }
    ]
}
```

**Response 200:**
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "ok",
    "message": "Playlists added successfully",
    "provider_response": { ... }
}
```

### 3.3 Delete Playlists

```
DELETE /api/credentials/{credential_id}/device/playlists/
```

**Response 200:**
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "ok",
    "message": "Playlists deleted successfully"
}
```

---

## 4. URL Routing

**`backend/api/urls.py`** — add:

```python
path('credentials/<int:credential_id>/device/', views.DeviceCheckView.as_view(), name='device-check'),
path('credentials/<int:credential_id>/device/playlists/', views.DevicePlaylistView.as_view(), name='device-playlists'),
```

---

## 5. Views

### DeviceCheckView (`GET`)

1. Get credential owned by `request.user`
2. Get the provider adapter via `get_adapter_for_provider(credential.order.product.provider)`
3. Call `adapter.check_device(mac)` with MAC from `credential.external_username`
4. Return device info

### DevicePlaylistView (`POST` / `DELETE`)

1. Get credential owned by `request.user`
2. Resolve adapter
3. If `POST`: validate input via `AddPlaylistSerializer`, call `adapter.add_playlists(mac, playlists)`
4. If `DELETE`: call `adapter.delete_playlists(mac)`
5. Return result

---

## 6. Serializers

### AddPlaylistSerializer
- `playlists: list[PlaylistEntrySerializer]` (min 1, max 50)

### PlaylistEntrySerializer
- `url: URLField` (required - M3U URL or Xtream URL)
- `name: CharField` (optional, max 100)

### DeviceInfoSerializer (output)
- `mac`, `status`, `expires_at`, `plan`, `playlist_count`, `provider_response`

---

## 7. Services Layer

New file: **`backend/api/device_services.py`**

```python
def get_credential_for_user(credential_id, user) -> Credential:
    """Fetch credential and verify ownership, raise 404 if not found."""
    return get_object_or_404(Credential, id=credential_id, order__reseller=user)

def get_device_adapter(credential: Credential):
    """Resolve the provider adapter for a credential's product provider."""
    return get_adapter_for_provider(credential.order.product.provider)

def check_device(credential: Credential) -> dict:
    adapter = get_device_adapter(credential)
    return adapter.check_device(credential.external_username)

def add_playlists(credential: Credential, playlists: list) -> dict:
    adapter = get_device_adapter(credential)
    return adapter.add_playlists(credential.external_username, playlists)

def delete_playlists(credential: Credential) -> dict:
    adapter = get_device_adapter(credential)
    return adapter.delete_playlists(credential.external_username)
```

---

## 8. Frontend Changes

### 8.1 New Page — `DeviceManagerPage.jsx`

Route: `/credentials/:credentialId/device`

**Sections:**
- **Device Info Panel**: MAC address, status, expiry, plan (from GET)
- **Refresh Button**: re-checks device
- **Playlists Section**:
  - List current playlists (from check response)
  - Form to add M3U URL + optional name
  - Delete all button with confirmation

### 8.2 ReceiptPage Update

For credentials belonging to HotPlayer products, add a **"Manage Device"** button
on each `CredentialCard` that links to `/credentials/{id}/device/`.

We can detect HotPlayer products via the `order.product.provider.adapter_key`
field — but the frontend currently doesn't have provider info on credentials.
**Option A**: Add `adapter_key` or `provider` info to the credential serializer.
**Option B**: Add a computed field to the credential response.

### 8.3 App Routing

```jsx
<Route path="/credentials/:credentialId/device" element={
    <ProtectedRoute>
        <DeviceManagerPage />
    </ProtectedRoute>
} />
```

### 8.4 API Helpers

Axios instance already handles auth. Frontend will call:
```javascript
await api.get(`/credentials/${credentialId}/device/`);
await api.post(`/credentials/${credentialId}/device/playlists/`, { playlists });
await api.delete(`/credentials/${credentialId}/device/playlists/`);
```

---

## 9. Admin Integration

Add admin actions to `CredentialAdmin` for manual device operations:

- **"Check Device"** action — calls `HotPlayerAdapter.check_device(mac)` and
  displays result in a message or a custom admin page
- **"Add Playlist"** action — shows a form to enter M3U URL and calls
  `add_playlists(mac, [...])`

These use the same service layer so admin actions always respect `USE_MOCK_PROVIDER`.

---

## 10. Phase-by-Phase Implementation

### Phase 1 — Backend Core (Base + Adapter + Services)
1. Extend `BaseProviderAdapter` with optional methods (NotImplementedError)
2. Implement `HotPlayerAdapter.check_device()`, `.add_playlists()`, `.delete_playlists()`
3. Implement `MockProviderAdapter` mock versions
4. Create `device_services.py`

### Phase 2 — REST API (Views + Serializers + URLs)
1. Create `DeviceCheckView`, `DevicePlaylistView`
2. Create serializers (`AddPlaylistSerializer`, `DeviceInfoSerializer`)
3. Register URLs
4. Add credential serializer to expose adapter_key for frontend
5. Add `NotImplementedError` handling → return 400 with message

### Phase 3 — Frontend
1. Build `DeviceManagerPage.jsx` with device info + playlist management
2. Update `CredentialCard` or `ReceiptPage` to link to device management
3. Add route to `App.jsx`
4. Handle loading/error/empty states

### Phase 4 — Admin
1. Add custom admin actions to `CredentialAdmin`
2. Add custom admin views if needed (for complex forms)

### Phase 5 — Verification
1. Test with `USE_MOCK_PROVIDER=True` — all endpoints return mock data
2. Verify error handling: unsupported provider → 400 with message
3. Verify auth: other user's credential → 404
4. Verify HotPlayer if possible via `docker-compose exec` (manual test with real API)

---

## 11. Risk Assessment

| Risk | Impact | Probability | Mitigation |
|------|--------|------------|------------|
| HotPlayer API changes endpoint paths | High | Low | Adapter encapsulates paths — single file to update |
| Accidental real API calls during dev | High | Medium | `USE_MOCK_PROVIDER=True` is always checked in `get_adapter_for_provider()` |
| New frontend route breaks existing routing | Low | Low | ProtectedRoute wrapper, standard pattern |
| Reseller accesses another's credential | High | Low | Ownership check in `get_credential_for_user()` via `order__reseller=request.user` |
| Network timeout on slow HotPlayer API | Medium | Low | Request timeout already configured in adapter |

### Rollback Strategy

- **Backend**: Remove the new URL patterns. No migration needed (no new models).
- **Frontend**: Remove the route and the "Manage Device" links. No dependency changes.
- **Full rollback**: Revert the commit on the deployment branch.

---

## 12. Mock Data Format

**`MockProviderAdapter.check_device(mac)`** returns:
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "active",
    "expires_at": "2026-07-08T00:00:00Z",
    "plan": "MONTHS_6",
    "playlist_count": 2,
    "provider_response": {"mock": true, "simulated": true}
}
```

**`MockProviderAdapter.add_playlists(mac, playlists)`** returns:
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "ok",
    "message": "Mock: 1 playlist(s) added successfully",
    "provider_response": {"mock": true}
}
```

**`MockProviderAdapter.delete_playlists(mac)`** returns:
```json
{
    "mac": "00:1A:79:AB:CD:EF",
    "status": "ok",
    "message": "Mock: All playlists deleted successfully",
    "provider_response": {"mock": true}
}
```

Respects `MOCK_FAIL_RATE` for simulated errors.

---

## 13. Files Changed (Complete List)

| File | Change Type |
|------|-------------|
| `backend/api/providers/base.py` | Add 3 optional methods with NotImplementedError |
| `backend/api/providers/hotplayer.py` | Implement 3 new API methods |
| `backend/api/providers/mock.py` | Implement 3 mock methods |
| `backend/api/providers/__init__.py` | No change (factory is generic) |
| `backend/api/device_services.py` | **NEW** — service functions |
| `backend/api/serializers.py` | Add 3 new serializers |
| `backend/api/views.py` | Add 2 new views |
| `backend/api/urls.py` | Add 2 new URL patterns |
| `backend/api/admin.py` | Add device management admin actions |
| `frontend/src/pages/DeviceManagerPage.jsx` | **NEW** — device management UI |
| `frontend/src/App.jsx` | Add route |
| `frontend/src/pages/ReceiptPage.jsx` | Add "Manage Device" link |
| `frontend/src/components/CredentialCard.jsx` | Optional: pass provider type prop |

---

## 14. HotPlayer API Contract (Assumed)

Based on standard REST patterns and the existing `/activate` endpoint:

| Endpoint | Method | Path | Auth Header | Request Body | Response |
|----------|--------|------|-------------|--------------|----------|
| Activate (existing) | POST | `/activate` | ApiKey | `{mac, pack_id, duration}` | `{status, user_id, ...}` |
| Check Device | GET | `/check-device/{mac}` | ApiKey | — | `{status, expires_at, plan, playlists, ...}` |
| Add Playlists | POST | `/add-playlists/{mac}` | ApiKey | `{playlists: [{url, name}]}` | `{status, message}` |
| Delete Playlists | DELETE | `/delete-playlists/{mac}` | ApiKey | — | `{status, message}` |

If the actual paths differ (e.g. `/api/check-device/{mac}`), only
`hotplayer.py` paths need updating — no other file changes.

---

## 15. Key Design Decisions Summary

1. **Base adapter gets optional methods** (not abstract) — avoids breaking existing adapters
2. **Credential-resource scoping** — MAC lives in credential, endpoints mirror that hierarchy
3. **No new models** — device state is transient, managed by HotPlayer
4. **`device_services.py`** — keeps views thin, follows existing service layer pattern (`services.py`)
5. **Frontend route under `/credentials/:id/device`** — clean, hierarchical, matches API
6. **Mock respects `MOCK_FAIL_RATE`** — consistent with existing mock behavior
