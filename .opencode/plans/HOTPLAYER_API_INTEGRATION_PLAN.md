# HotPlayer Device Management — Final Implementation Plan

Based on three confirmed design decisions:

1. **Reseller self-service extend** — dashboard activate extends existing MACs (credits deducted)
2. **Credential-scoped URLs** — `/api/credentials/<id>/device/*`
3. **Base adapter + NotImplementedError** — clean contract for future providers

---

## Two Purchase Paths (How They Coexist)

| Path | Trigger | MAC Source | `extend` | Use Case |
|---|---|---|---|---|
| **Catalog Purchase** (existing `create_line`) | Buy Now on product card | Auto-generated | `false` | Selling new subscriptions in bulk |
| **Device Dashboard** (new `activate_device`) | Reseller enters MAC manually | Manual entry | `false` for new, `true` for renewal | Managing existing customers, renewals, extending active devices |

---

## Files Changed

| File | Change |
|---|---|
| `backend/api/providers/base.py` | Add 4 optional methods: `check_device`, `add_playlists`, `delete_playlists`, `activate_device` (NotImplementedError) |
| `backend/api/providers/hotplayer.py` | Implement all 4 + refactor common HTTP logic into helper |
| `backend/api/providers/mock.py` | Implement mock versions of all 4 methods |
| `backend/api/device_services.py` | **NEW** — service functions with credit reservation |
| `backend/api/serializers.py` | Add `DeviceActivateSerializer`, `AddPlaylistsSerializer`, expose `provider_adapter_key` on `CredentialSerializer` |
| `backend/api/views.py` | Add 4 views tied to credential ownership |
| `backend/api/urls.py` | Add credential-scoped URL patterns |
| `backend/api/admin.py` | Add device management admin actions |
| `frontend/src/pages/DeviceManagerPage.jsx` | **NEW** — device management UI |
| `frontend/src/pages/ReceiptPage.jsx` | Add "Manage Device" link on HotPlayer credentials |
| `frontend/src/App.jsx` | Add route |

---

## Phase 1: Base Provider Adapter Extension

**`backend/api/providers/base.py`** — add optional methods:

```python
def check_device(self, mac: str) -> dict:
    raise NotImplementedError(f"Device check not supported by {self.provider.name}")

def add_playlists(self, mac: str, playlists: list) -> dict:
    raise NotImplementedError(f"Playlist management not supported by {self.provider.name}")

def delete_playlists(self, mac: str) -> dict:
    raise NotImplementedError(f"Playlist deletion not supported by {self.provider.name}")

def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
    raise NotImplementedError(f"Manual activation not supported by {self.provider.name}")
```

---

## Phase 2: HotPlayerAdapter

**`backend/api/providers/hotplayer.py`** — add 4 new methods.

The existing `create_line` stays untouched for catalog purchases. The new
`activate_device` is for dashboard use.

All methods use the same `ApiKey` header and error handling pattern as
`create_line`. The base URL is derived from `self.api_url` (which currently
points to `/activate`) — strip the path segment to get the root.

### activate_device

```python
def activate_device(self, mac: str, pack_id: int, duration: str, extend: bool = False) -> dict:
    """
    POST /activate with optional extend flag.
    duration: 'MONTHS_1', 'MONTHS_3', 'MONTHS_6', 'MONTHS_12', 'YEAR_1', 'FOREVER'
    extend: False -> new activation, True -> add time to existing MAC
    """
    payload = {"mac": mac, "pack_id": pack_id, "duration": duration, "extend": extend}
    # ... same requests pattern with ApiKey header ...
    # returns normalized dict like create_line but with provider_response intact
```

### check_device

```python
def check_device(self, mac: str) -> dict:
    """GET /check-device/{mac}"""
    url = f"{self.api_root}/check-device/{mac}"
    # GET with ApiKey header
    # Returns device info dict {mac, status, expiration, plan, playlists, ...}
```

### add_playlists

```python
def add_playlists(self, mac: str, playlists: list) -> dict:
    """POST /add-playlists/{mac}"""
    url = f"{self.api_root}/add-playlists/{mac}"
    payload = {"playlists": playlists}
    # POST with ApiKey header
    # Max 5 playlists enforced at serializer level
```

### delete_playlists

```python
def delete_playlists(self, mac: str) -> dict:
    """DELETE /delete-playlists/{mac}"""
    url = f"{self.api_root}/delete-playlists/{mac}"
    # DELETE with ApiKey header
```

---

## Phase 3: MockProviderAdapter

**`backend/api/providers/mock.py`** — add mock implementations that respect
`MOCK_FAIL_RATE`:

```python
def activate_device(self, mac, pack_id, duration, extend=False):
    if random.random() < self.fail_rate:
        raise Exception(f"Simulated provider failure: activate_device")
    return {'status': 'success', 'mac': mac, 'balance': 100, 'mock': True}

def check_device(self, mac):
    if random.random() < self.fail_rate:
        raise Exception(f"Simulated provider failure: check_device")
    from datetime import timedelta
    from django.utils import timezone
    return {
        'status': 'active', 'mac': mac, 'plan': 'MONTHS_6',
        'expiration': (timezone.now() + timedelta(days=180)).isoformat(),
        'playlists': [{'name': 'Mock Playlist', 'url': 'http://mock.example.com'}],
        'mock': True
    }

def add_playlists(self, mac, playlists):
    if random.random() < self.fail_rate:
        raise Exception(f"Simulated provider failure: add_playlists")
    return {'status': 'success', 'playlists_added': len(playlists), 'mock': True}

def delete_playlists(self, mac):
    if random.random() < self.fail_rate:
        raise Exception(f"Simulated provider failure: delete_playlists")
    return {'status': 'success', 'message': 'All playlists deleted', 'mock': True}
```

---

## Phase 4: Services Layer

**`backend/api/device_services.py`** — **NEW FILE**

```python
from decimal import Decimal
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.conf import settings
from .models import Credential, ProductVariant, CustomUser, CreditTransaction, Order
from .providers import get_adapter_for_provider


class InsufficientCredits(Exception):
    pass


def get_credential_for_user(credential_id, user):
    return get_object_or_404(Credential, id=credential_id, order__reseller=user)


def activate_device(credential_id, user, pack_id, duration, extend, quantity=1):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    mac = credential.streaming_username or credential.external_username

    variant = ProductVariant.objects.filter(
        product=credential.order.product,
        external_pack_id=pack_id,
        is_active=True,
    ).first()
    if not variant:
        raise ValueError("No matching variant found for this pack_id")

    total = variant.price_in_credits * Decimal(str(quantity))

    with transaction.atomic():
        reseller = CustomUser.objects.select_for_update().get(id=user.id)
        if reseller.credit_balance < total:
            raise InsufficientCredits(
                f"Insufficient credits. Required: {total}, Available: {reseller.credit_balance}"
            )
        reseller.credit_balance -= total
        reseller.save()

        CreditTransaction.objects.create(
            reseller=reseller,
            delta=-total,
            balance_after=reseller.credit_balance,
            actor=CreditTransaction.Actor.RESELLER,
            reason=f"Device activation/extend for MAC {mac} (credential #{credential_id})",
        )

    try:
        result = adapter.activate_device(mac, pack_id, duration, extend)
    except Exception:
        # Refund credits on provider failure
        with transaction.atomic():
            reseller = CustomUser.objects.select_for_update().get(id=user.id)
            reseller.credit_balance += total
            reseller.save()
            CreditTransaction.objects.create(
                reseller=reseller,
                delta=total,
                balance_after=reseller.credit_balance,
                actor=CreditTransaction.Actor.SYSTEM,
                reason=f"Refund for failed device activation (MAC {mac})",
            )
        raise

    return {'result': result, 'credential': credential, 'variant': variant}


def check_device(credential_id, user):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    mac = credential.streaming_username or credential.external_username
    return adapter.check_device(mac)


def add_playlists(credential_id, user, playlists):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    mac = credential.streaming_username or credential.external_username
    return adapter.add_playlists(mac, playlists)


def delete_playlists(credential_id, user):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    mac = credential.streaming_username or credential.external_username
    return adapter.delete_playlists(mac)
```

---

## Phase 5: Serializers

`backend/api/serializers.py` — add:

```python
class DeviceActivateSerializer(serializers.Serializer):
    pack_id = serializers.IntegerField()
    duration = serializers.ChoiceField(choices=[
        'MONTHS_1', 'MONTHS_3', 'MONTHS_6',
        'MONTHS_12', 'YEAR_1', 'FOREVER',
    ])
    extend = serializers.BooleanField(default=False)

class PlaylistEntrySerializer(serializers.Serializer):
    url = serializers.URLField()
    name = serializers.CharField(max_length=100, required=False, default='Playlist')

class AddPlaylistsSerializer(serializers.Serializer):
    playlists = serializers.ListField(
        child=PlaylistEntrySerializer(),
        min_length=1,
        max_length=5,
    )
```

Also expose `provider_adapter_key` on `CredentialSerializer` so the frontend
knows whether to show the "Manage Device" link. Add to existing serializer:

```python
class CredentialSerializer(serializers.ModelSerializer):
    password = serializers.SerializerMethodField()
    provider_adapter_key = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ['id', 'username', 'password', 'dns_domain', 'm3u_url',
                  'expires_at', 'provider_adapter_key']

    def get_provider_adapter_key(self, obj):
        return obj.order.product.provider.adapter_key if obj.order.product.provider else None
```

---

## Phase 6: Views

**`backend/api/views.py`** — add 4 new views. All follow this pattern:
1. Resolve credential (auto-auth: `order__reseller=request.user`)
2. Handle `NotImplementedError` -> 501
3. Handle `InsufficientCredits` -> 400 (for activate)
4. Handle provider errors -> 400

### CredentialDeviceStatusView
- `GET /api/credentials/<id>/device/status/`

### CredentialDeviceActivateView
- `POST /api/credentials/<id>/device/activate/`
- Requires `Idempotency-Key` header (reuse existing `check_idempotency`)
- Rate-limited via `PurchaseThrottle` (reuse existing)

### CredentialDevicePlaylistsView
- `POST /api/credentials/<id>/device/playlists/` — validates max 5 playlists
- `DELETE /api/credentials/<id>/device/playlists/`

---

## Phase 7: URL Routing

**`backend/api/urls.py`** — add:

```python
path('credentials/<int:credential_id>/device/status/',
     views.CredentialDeviceStatusView.as_view(), name='credential-device-status'),
path('credentials/<int:credential_id>/device/activate/',
     views.CredentialDeviceActivateView.as_view(), name='credential-device-activate'),
path('credentials/<int:credential_id>/device/playlists/',
     views.CredentialDevicePlaylistsView.as_view(), name='credential-device-playlists'),
```

---

## Phase 8: Frontend

### DeviceManagerPage.jsx — New Page

Route: `/credentials/:credentialId/manage`

**Sections:**

1. **Device Info Card** — MAC, plan, expiry, status (from GET status/)
2. **Activate/Extend Section:**
   - "Extend 12 Months" button -> POST activate with `extend=true, duration=YEAR_1`
   - "Extend Lifetime" button -> POST activate with `extend=true, duration=FOREVER`
3. **Add Playlists Form** — dynamic list of URL + name fields (max 5), save button
4. **Delete All Playlists** — button with confirmation dialog
5. **Message/Error Toast**

### CredentialSerializer Update

Frontend needs `provider_adapter_key` on each credential to know whether to show
"Manage Device" link. This is added in Phase 5.

### ReceiptPage Update

For each credential where `cred.provider_adapter_key === 'hotplayer'`, add a
**"Manage Device"** link -> `/credentials/{cred.id}/manage`

### App.jsx

```jsx
import DeviceManagerPage from './pages/DeviceManagerPage';
...
<Route path="/credentials/:credentialId/manage" element={
    <ProtectedRoute><DeviceManagerPage /></ProtectedRoute>
} />
```

---

## Phase 9: Admin Actions

**`backend/api/admin.py`** — add to `CredentialAdmin`:

- **"Check device"** action — selects credentials -> calls `check_device(mac)` for
  each -> displays results as admin messages
- **"Add playlist"** action — intermediate form page to enter URL -> calls
  `add_playlists(mac, [url])`

Admins manage ANY credential (no ownership filter). Use
`get_adapter_for_provider()` directly (safe under mock mode).

---

## Phase 10: Gaps from Original Draft — All Addressed

| Gap | Fix |
|---|---|
| No base adapter methods | Added to `BaseProviderAdapter` with `NotImplementedError` |
| No ownership auth | Auto-auth via `credential.order__reseller=request.user` |
| No mock implementations | Full mock for all 4 methods, respects `MOCK_FAIL_RATE` |
| `activate_device` doesn't consume credits | Credit reservation + refund on failure in `device_services.py` |
| `extend` not used | `activate_device` takes `extend` param, maps to HotPlayer API |
| No rate limiting | Reuse `PurchaseThrottle` on activate view |
| Weak error handling | `NotImplementedError` -> 501, provider errors -> 400, creditsafety -> 400 |
| Provider info missing on frontend | `provider_adapter_key` exposed via `CredentialSerializer` |
| MAC validation | Validate MAC format in activate view before provider call |

---

## Risk Assessment

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| HotPlayer API changes paths | High | Low | Paths encapsulated in adapter |
| Accidental real API calls during dev | High | Medium | `USE_MOCK_PROVIDER` enforced by factory |
| Credit deducted but provider fails | High | Low | Atomic tx + refund in except block |
| Reseller manages another's credential | High | Low | Ownership check in `get_credential_for_user()` |
| Provider doesn't support device ops | Medium | Medium | `NotImplementedError` -> 501 with message |

---

## Implementation Order

```
Phase 1: Base adapter extension (base.py)
    |
    v
Phase 2: HotPlayerAdapter (4 methods + api_root helper)
    |
    v
Phase 3: MockProviderAdapter (4 mock methods)
    |
    v
Phase 4: device_services.py
    |
    v
Phase 5: Serializers
    |
    v
Phase 6: Views + URL routing
    |
    v
Phase 7: Admin actions
    |
    v
Phase 8: Frontend (DeviceManagerPage + ReceiptPage link + route)
    |
    v
Phase 9: Test with USE_MOCK_PROVIDER=True
```

---

## Ready to Implement?

This plan is internally consistent, addresses all gaps, and respects the three
design decisions you confirmed. When you say go, I'll start with Phase 1.
