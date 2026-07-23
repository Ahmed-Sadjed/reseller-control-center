from datetime import datetime, timezone
from django.shortcuts import get_object_or_404
from .models import Credential, Provider
from .providers import get_adapter_for_provider


def get_credential_for_user(credential_id, user):
    return get_object_or_404(Credential, id=credential_id, order__reseller=user)


def check_device_by_mac(mac, user):
    provider = Provider.objects.filter(adapter_key='hotplayer', is_active=True).first()
    if not provider:
        return {
            'found': False,
            'mac': mac,
            'status': 'error',
            'message': 'No active HotPlayer provider configured.',
        }

    adapter = get_adapter_for_provider(provider)

    try:
        result = adapter.check_device(mac)
    except Exception as e:
        err_msg = str(e)
        if 'MAC not found' in err_msg:
            err_msg = f'{mac}\nMAC not found. Maybe HotIPTV application is not yet installed on this device!'
        else:
            err_msg = f'{mac}\n{err_msg}'
        return {
            'found': False,
            'mac': mac,
            'status': 'error',
            'message': err_msg,
        }

    if result.get('status') == 'failed':
        api_msg = result.get('message', 'MAC not found')
        if 'MAC not found' in api_msg:
            api_msg = 'MAC not found. Maybe HotIPTV application is not yet installed on this device!'
        return {
            'found': False,
            'mac': mac,
            'status': 'not_found',
            'message': f'{mac}\n{api_msg}',
        }

    plan_raw = result.get('plan', '')
    plan_mapping = {'YEAR_1': '1 Year', 'FOREVER': 'Lifetime'}
    plan = plan_mapping.get(plan_raw, plan_raw)

    expiration_ms = result.get('expiration')

    if expiration_ms and plan != 'Lifetime':
        try:
            expires_at_dt = datetime.fromtimestamp(int(expiration_ms) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            expires_at_dt = datetime.fromisoformat(expiration_ms)
        expires_at = expires_at_dt.strftime('%B %d, %Y')
        now = datetime.now(timezone.utc)
        delta = expires_at_dt - now
        days_remaining = max(0, delta.days)

        if days_remaining == 0 and delta.total_seconds() <= 0:
            status = 'expired'
        elif days_remaining <= 7:
            status = 'expiring_soon'
        else:
            status = 'active'
    else:
        expires_at = None
        days_remaining = None
        status = 'lifetime'

    return {
        'found': True,
        'mac': mac,
        'plan': plan,
        'expires_at': expires_at,
        'days_remaining': days_remaining,
        'status': status,
    }

