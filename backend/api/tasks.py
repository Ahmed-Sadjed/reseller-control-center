from django_rq import job

from .services import fulfill_sync


@job
def fulfill_order_async(order_id):
    from api.models import Order
    order = Order.objects.get(id=order_id)
    credentials, failure = fulfill_sync(order)
    return {
        'order_id': str(order.uuid),
        'status': order.status,
        'failure_reason': failure,
    }
