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
            product_name_at_purchase=f"{product.name} - {'Lifetime' if variant.is_lifetime else variant.get_duration_months_display()}",
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


def fulfill_sync(order: Order, provider=None, mac='', note='', username='', password='', template_id=None, dns_domain_id=None):
    product = order.product

    # ── Manual product flow: assign pre-loaded credentials ──
    if product.is_manual:
        return _fulfill_manual(order)

    # ── API-driven product flow: call provider adapter ──
    if provider is None:
        provider = get_adapter_for_provider(order.product.provider)
    credentials = []
    failure_reason = None

    for idx in range(order.quantity):
        try:
            result = provider.create(
                pack_id=order.variant.external_pack_id,
                months=order.variant.duration_months,
                is_lifetime=order.variant.is_lifetime,
                mac=mac,
                note=note,
                username=username,
                password=password,
                template_id=template_id,
                dns_domain_id=dns_domain_id,
            )
            cred_data = result.get('credentials', {})
            non_secret_data = {}
            secret_password = ''
            for key, value in cred_data.items():
                if key.startswith('secret_'):
                    secret_password = value
                else:
                    non_secret_data[key] = value

            external_username = result.get('external_id', '')
            streaming_username = cred_data.get('username', cred_data.get('mac', external_username))

            cred = Credential.objects.create(
                order=order,
                external_username=external_username,
                streaming_username=streaming_username,
                encrypted_password=encrypt_password(secret_password),
                dns_domain=cred_data.get('dns_domain', ''),
                m3u_url=cred_data.get('m3u_url', ''),
                data=non_secret_data,
                expires_at=result.get('expires_at'),
            )
            credentials.append(cred)
        except Exception as e:
            failure_reason = str(e)
            break

    if failure_reason is None:
        order.status = Order.Status.COMPLETED
        order.save()
        return credentials, None

    if credentials:
        processed = len(credentials)
        total_original = order.quantity
        with transaction.atomic():
            refund_amount = order.unit_price_at_purchase * Decimal(str(total_original - processed))
            reseller = CustomUser.objects.select_for_update().get(id=order.reseller_id)
            reseller.credit_balance += refund_amount
            reseller.save()
            CreditTransaction.objects.create(
                reseller=reseller,
                delta=refund_amount,
                balance_after=reseller.credit_balance,
                actor=CreditTransaction.Actor.SYSTEM,
                reason=f"Partial refund for {total_original - processed} unprocessed item(s) in order #{order.uuid}",
                reference_order=order,
            )
            order.quantity = processed
            order.total_credits = order.unit_price_at_purchase * Decimal(str(processed))
            order.status = Order.Status.COMPLETED
            order.failure_reason = f"Partial fulfillment: processed {processed}/{total_original} items. Error on item {processed + 1}: {failure_reason}"
            order.save()
        return credentials, failure_reason

    compensate_order(order, failure_reason)
    return [], failure_reason


def _fulfill_manual(order: Order):
    """
    Fulfill an order for a manual product by assigning pre-loaded
    ManualProductCredentials from the dashboard inventory.
    """
    from dashboard.models import ManualProductCredential

    credentials = []
    failure_reason = None

    for idx in range(order.quantity):
        with transaction.atomic():
            manual_cred = (
                ManualProductCredential.objects
                .filter(product=order.product, status='available')
                .select_for_update(skip_locked=True)
                .first()
            )

            if not manual_cred:
                failure_reason = f"Product '{order.product.name}' is out of stock (no available credentials)."
                break

            # Mark the manual credential as used
            manual_cred.status = ManualProductCredential.Status.USED
            manual_cred.assigned_to = order.reseller
            manual_cred.assigned_at = timezone.now()
            manual_cred.used_at = timezone.now()
            manual_cred.save()

            # Build credential data based on type
            cred_data = {'manual': True, 'credential_type': manual_cred.credential_type}
            secret_password = ''
            if manual_cred.credential_type == 'username_password':
                cred_data['username'] = manual_cred.username
                secret_password = manual_cred.password
                streaming_username = manual_cred.username
            else:
                cred_data['code'] = manual_cred.code
                streaming_username = manual_cred.code[:50]

            if manual_cred.notes:
                cred_data['notes'] = manual_cred.notes

            cred = Credential.objects.create(
                order=order,
                external_username=f"manual-{manual_cred.id}",
                streaming_username=streaming_username,
                encrypted_password=encrypt_password(secret_password),
                dns_domain='',
                m3u_url='',
                data=cred_data,
                expires_at=manual_cred.expires_at,
            )
            credentials.append(cred)

    if failure_reason is None:
        order.status = Order.Status.COMPLETED
        order.save()
        return credentials, None

    if credentials:
        processed = len(credentials)
        total_original = order.quantity
        with transaction.atomic():
            refund_amount = order.unit_price_at_purchase * Decimal(str(total_original - processed))
            reseller = CustomUser.objects.select_for_update().get(id=order.reseller_id)
            reseller.credit_balance += refund_amount
            reseller.save()
            CreditTransaction.objects.create(
                reseller=reseller,
                delta=refund_amount,
                balance_after=reseller.credit_balance,
                actor=CreditTransaction.Actor.SYSTEM,
                reason=f"Partial fulfillment: {processed}/{total_original} credentials available for order #{order.uuid}",
                reference_order=order,
            )
            order.quantity = processed
            order.total_credits = order.unit_price_at_purchase * Decimal(str(processed))
            order.status = Order.Status.COMPLETED
            order.failure_reason = f"Partial: {processed}/{total_original} items fulfilled. {failure_reason}"
            order.save()
        return credentials, failure_reason

    compensate_order(order, failure_reason)
    return [], failure_reason


def compensate_order(order: Order, failure_reason: str):
    with transaction.atomic():
        for cred in Credential.objects.filter(order=order):
            QuarantinedCredential.objects.create(
                order=order,
                username=cred.external_username,
                encrypted_password=cred.encrypted_password,
                provider_response=cred.data,
                reason=f"Order failed: {failure_reason}",
            )
            cred.delete()
        reseller = CustomUser.objects.select_for_update().get(id=order.reseller_id)
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
