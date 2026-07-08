from decimal import Decimal
from django.db import transaction
from django.shortcuts import get_object_or_404
from .models import Credential, ProductVariant, CustomUser, CreditTransaction
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
        result = adapter.activate_device(mac, pack_id, duration, extend)
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
