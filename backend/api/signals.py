from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.postgres.search import SearchVector
from .models import Product, ProductVariant, Category


@receiver([post_save, post_delete], sender=Product)
@receiver([post_save, post_delete], sender=ProductVariant)
@receiver([post_save, post_delete], sender=Category)
def invalidate_catalog_cache(sender, **kwargs):
    cache.delete_pattern('product_list:*')
    cache.delete_pattern('category_list:*')
    cache.delete_pattern('stats:*')


@receiver(post_save, sender=Product)
def update_search_vector(sender, instance, **kwargs):
    Product.objects.filter(pk=instance.pk).update(
        search_vector=SearchVector('name', weight='A', config='simple')
        + SearchVector('description', weight='B', config='simple')
    )
