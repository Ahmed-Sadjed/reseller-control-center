from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from .models import CustomUser, Order, Credential, CreditTransaction, IdempotencyKey, QuarantinedCredential
from .utils import encrypt_password, build_m3u_url
from .providers import get_provider_adapter


class InsufficientCredits(Exception):
    pass


class IdempotencyReplay(Exception):
    def __init__(self, order):
        self.order = order


def reserve_phase(reseller: CustomUser, product, quantity: int, idempotency_key: str) -> Order:
    with transaction.atomic():
        reseller = CustomUser.objects.select_for_update().get(id=reseller.id)
        total = product.price_in_credits * Decimal(str(quantity))
        if reseller.credit_balance < total:
            raise InsufficientCredits(
                f"Insufficient credits. Required: {total}, Available: {reseller.credit_balance}"
            )
        reseller.credit_balance -= total
        reseller.save()
        order = Order.objects.create(
            reseller=reseller,
            product=product,
            quantity=quantity,
            unit_price_at_purchase=product.price_in_credits,
            product_name_at_purchase=product.name,
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
        provider = get_provider_adapter()
    credentials = []
    failed_at = None
    failure_reason = None

    for idx in range(order.quantity):
        try:
            data = provider.create_line(
                pack_id=order.product.external_pack_id,
                months=order.product.duration_months,
            )
            cred = Credential.objects.create(
                order=order,
                external_username=data['username'],
                encrypted_password=encrypt_password(data['password']),
                dns_domain=build_m3u_url(data['username'], data['password']),
                expires_at=timezone.now() + timedelta(days=30 * order.product.duration_months),
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
        compensate_order(order, failure_reason)
        return [], failure_reason


def compensate_order(order: Order, failure_reason: str):
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
