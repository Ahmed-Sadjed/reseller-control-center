from django_rq import job

from .services import fulfill_sync


@job
def fulfill_order_async(order_id, **kwargs):
    from api.models import Order
    order = Order.objects.get(id=order_id)
    credentials, failure = fulfill_sync(order, **kwargs)
    return {
        'order_id': str(order.uuid),
        'status': order.status,
        'failure_reason': failure,
    }
