from decimal import Decimal
from datetime import datetime, timezone
from django.db import transaction
from django.shortcuts import get_object_or_404
from .models import Credential, ProductVariant, CustomUser, CreditTransaction, Provider
from .providers import get_adapter_for_provider


class InsufficientCredits(Exception):
    pass


class NoMatchingVariant(Exception):
    pass


def get_credential_for_user(credential_id, user):
    return get_object_or_404(Credential, id=credential_id, order__reseller=user)


def activate_device(credential_id, user, pack_id, duration, extend=False, quantity=1):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    mac = credential.streaming_username or credential.external_username

    variant = ProductVariant.objects.filter(
        product=credential.order.product,
        external_pack_id=pack_id,
        is_active=True,
    ).first()
    if not variant:
        raise NoMatchingVariant(f"No active variant found for pack_id={pack_id}")

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
        result = adapter.activate_device(mac, pack_id, duration, extend, credential=credential)
    except Exception:
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
    return adapter.check_device(mac, credential=credential)


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


def refund_device(credential_id, user):
    credential = get_credential_for_user(credential_id, user)
    adapter = get_adapter_for_provider(credential.order.product.provider)
    
    if 'refund' not in adapter.capabilities:
        raise NotImplementedError(f"Refund not supported by {credential.order.product.provider.name}")

    with transaction.atomic():
        # Call provider refund
        result = adapter.refund(credential)
        
        order = credential.order
        total = order.total_credits
        
        # Refund credits to user
        reseller = CustomUser.objects.select_for_update().get(id=user.id)
        reseller.credit_balance += total
        reseller.save()
        
        CreditTransaction.objects.create(
            reseller=reseller,
            delta=total,
            balance_after=reseller.credit_balance,
            actor=CreditTransaction.Actor.SYSTEM,
            reason=f"Refund for order #{order.uuid}",
        )
        
        # Update statuses
        order.status = 'REFUNDED'
        order.save()
        
        credential.is_revoked = True
        credential.save()
        
    return {'result': result, 'credential': credential, 'refunded_credits': total}
