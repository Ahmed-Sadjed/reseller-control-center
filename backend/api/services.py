from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from .models import CustomUser, Order, Credential, CreditTransaction, IdempotencyKey, QuarantinedCredential
from .utils import encrypt_password
from .providers import get_adapter_for_provider


class InsufficientCredits(Exception):
    pass


class IdempotencyReplay(Exception):
    def __init__(self, order):
        self.order = order


def reserve_phase(reseller: CustomUser, variant, quantity: int, idempotency_key: str) -> Order:
    product = variant.product
    with transaction.atomic():
        reseller = CustomUser.objects.select_for_update().get(id=reseller.id)
        total = variant.price_in_credits * Decimal(str(quantity))
        if reseller.credit_balance < total:
            raise InsufficientCredits(
                f"Insufficient credits. Required: {total}, Available: {reseller.credit_balance}"
            )
        reseller.credit_balance -= total
        reseller.save()
        order = Order.objects.create(
            reseller=reseller,
            product=product,
            variant=variant,
            quantity=quantity,
            unit_price_at_purchase=variant.price_in_credits,
            product_name_at_purchase=f"{product.name} - {variant.get_duration_months_display()}",
            total_credits=total,
            status=Order.Status.PENDING,
            idempotency_key=idempotency_key,
        )
        CreditTransaction.objects.create(
            reseller=reseller,
            delta=-total,
            balance_after=reseller.credit_balance,
            actor=CreditTransaction.Actor.RESELLER,
            reason=f"Purchase #{order.uuid}",
            reference_order=order,
        )
        IdempotencyKey.objects.create(
            reseller=reseller,
            key=idempotency_key,
            order=order,
        )
        return order


def fulfill_sync(order: Order, provider=None):
    if provider is None:
        provider = get_adapter_for_provider(order.product.provider)
    credentials = []
    failed_at = None
    failure_reason = None

    for idx in range(order.quantity):
        try:
            data = provider.create_line(
                pack_id=order.variant.external_pack_id,
                months=order.variant.duration_months,
                is_lifetime=order.variant.is_lifetime,
            )
            cred = Credential.objects.create(
                order=order,
                external_username=data['user_id'],
                streaming_username=data.get('streaming_username', ''),
                encrypted_password=encrypt_password(data['password']),
                dns_domain=data.get('dns_domain', ''),
                m3u_url=data.get('m3u_url', ''),
                expires_at=data.get('expires_at'),
            )
            credentials.append(cred)
        except Exception as e:
            failed_at = idx + 1
            failure_reason = str(e)
            break

    if failed_at is None:
        order.status = Order.Status.COMPLETED
        order.save()
        return credentials, None
    else:
        compensate_order(order, failure_reason, credentials)
        return [], failure_reason


def compensate_order(order: Order, failure_reason: str, successful_credentials=None):
    with transaction.atomic():
        for cred in Credential.objects.filter(order=order):
            QuarantinedCredential.objects.create(
                order=order,
                username=cred.external_username,
                encrypted_password=cred.encrypted_password,
                provider_response={},
                reason=f"Order failed: {failure_reason}",
            )
            cred.delete()
        reseller = order.reseller
        reseller.credit_balance += order.total_credits
        reseller.save()
        CreditTransaction.objects.create(
            reseller=reseller,
            delta=order.total_credits,
            balance_after=reseller.credit_balance,
            actor=CreditTransaction.Actor.SYSTEM,
            reason=f"Refund for failed order #{order.uuid}",
            reference_order=order,
        )
        order.status = Order.Status.FAILED
        order.failure_reason = failure_reason
        order.save()


def check_idempotency(reseller: CustomUser, key: str):
    try:
        idem = IdempotencyKey.objects.select_related('order').get(reseller=reseller, key=key)
        return idem.order
    except IdempotencyKey.DoesNotExist:
        return None
