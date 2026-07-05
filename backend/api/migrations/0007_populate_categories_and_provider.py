from django.db import migrations
from django.conf import settings


CATEGORY_MAP = {
    'IPTV': {'slug': 'iptv', 'sort_order': 0},
    'GAMING': {'slug': 'gaming', 'sort_order': 10},
    'STREAMING': {'slug': 'streaming', 'sort_order': 20},
}


def populate_categories(apps, schema_editor):
    Category = apps.get_model('api', 'Category')
    for name, attrs in CATEGORY_MAP.items():
        Category.objects.get_or_create(
            name=name,
            defaults={
                'slug': attrs['slug'],
                'sort_order': attrs['sort_order'],
                'is_active': True,
            },
        )


def link_products_to_categories(apps, schema_editor):
    Category = apps.get_model('api', 'Category')
    Product = apps.get_model('api', 'Product')

    category_map = {c.name: c for c in Category.objects.all()}

    for product in Product.objects.filter(category_old__isnull=False, category__isnull=True):
        cat = category_map.get(product.category_old)
        if cat:
            product.category = cat
            product.save(update_fields=['category'])


def seed_provider(apps, schema_editor):
    import os
    Provider = apps.get_model('api', 'Provider')

    api_url = os.environ.get('IPTV_API_URL', '')
    api_key = os.environ.get('IPTV_API_KEY', '')

    if api_url:
        Provider.objects.get_or_create(
            name='CMS-Only',
            defaults={
                'api_endpoint': api_url,
                'is_active': True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_category_provider_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_categories, migrations.RunPython.noop),
        migrations.RunPython(link_products_to_categories, migrations.RunPython.noop),
        migrations.RunPython(seed_provider, migrations.RunPython.noop),
    ]
