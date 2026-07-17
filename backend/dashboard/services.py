from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from api.models import CustomUser, Order, CreditTransaction, Provider
from .models import ManualProductCredential


def get_dashboard_stats():
    """Compute overview dashboard statistics."""
    now = timezone.now()
    reseller_qs = CustomUser.objects.filter(role='RESELLER')
    order_qs = Order.objects.all()
    cred_qs = ManualProductCredential.objects.all()

    return {
        'total_resellers': reseller_qs.count(),
        'active_resellers': reseller_qs.filter(is_active=True).count(),
        'total_orders': order_qs.count(),
        'completed_orders': order_qs.filter(status='COMPLETED').count(),
        'total_revenue': order_qs.filter(status='COMPLETED').aggregate(
            total=Sum('total_credits')
        )['total'] or Decimal('0.00'),
        'total_credentials': cred_qs.count(),
        'available_credentials': cred_qs.filter(status='available').count(),
    }


def get_top_resellers(limit=10):
    """Return top resellers ranked by completed order revenue."""
    return (
        CustomUser.objects.filter(role='RESELLER')
        .annotate(
            order_count=Count('orders', filter=Q(orders__status='COMPLETED')),
            total_revenue=Sum('orders__total_credits', filter=Q(orders__status='COMPLETED')),
        )
        .order_by('-total_revenue')[:limit]
    )


def get_recent_activity(limit=20):
    """Return interleaved recent orders and credit transactions."""
    recent_orders = (
        Order.objects.select_related('reseller')
        .order_by('-created_at')[:limit]
    )
    recent_transactions = (
        CreditTransaction.objects.filter(actor='ADMIN')
        .select_related('reseller')
        .order_by('-created_at')[:limit]
    )

    activities = []
    for order in recent_orders:
        activities.append({
            'type': 'order',
            'description': f"Order #{str(order.uuid)[:8]} — {order.product_name_at_purchase}",
            'amount': order.total_credits,
            'user': order.reseller.username,
            'status': order.status,
            'created_at': order.created_at,
        })
    for txn in recent_transactions:
        activities.append({
            'type': 'credit',
            'description': txn.reason,
            'amount': txn.delta,
            'user': txn.reseller.username,
            'status': None,
            'created_at': txn.created_at,
        })

    activities.sort(key=lambda x: x['created_at'], reverse=True)
    return activities[:limit]


def get_revenue_chart_data(months=12):
    """Return monthly revenue data for charting."""
    now = timezone.now()
    start = now - timedelta(days=months * 30)

    monthly = (
        Order.objects.filter(status='COMPLETED', created_at__gte=start)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(
            revenue=Sum('total_credits'),
            orders=Count('id'),
        )
        .order_by('month')
    )

    return [
        {
            'month': item['month'].strftime('%Y-%m'),
            'revenue': item['revenue'] or Decimal('0.00'),
            'orders': item['orders'],
        }
        for item in monthly
    ]


def get_provider_health():
    """Return health status for each active provider."""
    providers = Provider.objects.filter(is_active=True)
    results = []
    for provider in providers:
        # Count recent orders per provider
        recent_orders = Order.objects.filter(
            product__provider=provider,
            created_at__gte=timezone.now() - timedelta(hours=24),
        )
        total = recent_orders.count()
        failed = recent_orders.filter(status='FAILED').count()

        results.append({
            'id': provider.id,
            'name': provider.name,
            'adapter_key': provider.adapter_key,
            'is_active': provider.is_active,
            'orders_24h': total,
            'failed_24h': failed,
            'error_rate': round(failed / total * 100, 1) if total > 0 else 0,
        })
    return results


@transaction.atomic
def adjust_credits(reseller, amount, reason, admin_user):
    """
    Add or remove credits from a reseller's balance.
    Uses select_for_update for concurrency safety.
    """
    reseller = CustomUser.objects.select_for_update().get(id=reseller.id)

    if amount < 0 and reseller.credit_balance + amount < 0:
        raise ValueError(
            f"Cannot deduct {abs(amount)} credits. "
            f"Reseller only has {reseller.credit_balance} credits."
        )

    reseller.credit_balance += amount
    reseller.save()

    CreditTransaction.objects.create(
        reseller=reseller,
        delta=amount,
        balance_after=reseller.credit_balance,
        actor=CreditTransaction.Actor.ADMIN,
        reason=reason,
    )

    return reseller


def assign_manual_credential(product, reseller):
    """
    Find the next available credential for a manual product and assign it.
    Returns the credential or raises ValueError if out of stock.
    """
    credential = (
        ManualProductCredential.objects
        .filter(product=product, status='available')
        .select_for_update(skip_locked=True)
        .first()
    )

    if not credential:
        raise ValueError(f"Product '{product.name}' is out of stock (no available credentials).")

    credential.status = ManualProductCredential.Status.USED
    credential.assigned_to = reseller
    credential.assigned_at = timezone.now()
    credential.used_at = timezone.now()
    credential.save()

    return credential
