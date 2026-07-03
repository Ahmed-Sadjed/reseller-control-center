from collections import defaultdict
from django.db import migrations, models


KNOWN_SUFFIXES = [' 1 Month', ' 3 Months', ' 6 Months', ' 12 Months']


def strip_duration_suffix(name):
    for suffix in KNOWN_SUFFIXES:
        if name.endswith(suffix):
            base = name[:-len(suffix)]
            if base:
                return base
    return None


def consolidate_products(apps, schema_editor):
    Product = apps.get_model('api', 'Product')
    ProductVariant = apps.get_model('api', 'ProductVariant')

    active_products = Product.objects.filter(is_active=True)

    groups = defaultdict(list)
    standalone = []

    for prod in active_products:
        base = strip_duration_suffix(prod.name)
        if base:
            groups[base].append(prod)
        else:
            standalone.append(prod)

    for base_name, old_products in groups.items():
        first = old_products[0]
        master = Product.objects.create(
            name=base_name.strip(),
            category=first.category,
            description=first.description,
            is_active=True,
        )
        for old_prod in old_products:
            ProductVariant.objects.create(
                product=master,
                duration_months=old_prod.duration_months,
                external_pack_id=old_prod.external_pack_id,
                price_in_credits=old_prod.price_in_credits,
                is_active=old_prod.is_active,
            )
            old_prod.is_active = False
            old_prod.save()

    for prod in standalone:
        master = Product.objects.create(
            name=prod.name,
            category=prod.category,
            description=prod.description,
            is_active=True,
        )
        ProductVariant.objects.create(
            product=master,
            duration_months=prod.duration_months,
            external_pack_id=prod.external_pack_id,
            price_in_credits=prod.price_in_credits,
            is_active=prod.is_active,
        )
        prod.is_active = False
        prod.save()


def reverse_func(apps, schema_editor):
    Product = apps.get_model('api', 'Product')
    ProductVariant = apps.get_model('api', 'ProductVariant')

    for variant in ProductVariant.objects.select_related('product').all():
        old_prod = Product.objects.filter(
            is_active=False,
            duration_months=variant.duration_months,
            name__startswith=variant.product.name,
        ).first()
        if old_prod:
            old_prod.is_active = True
            old_prod.save()
        variant.delete()

    Product.objects.filter(external_pack_id__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_productvariant_and_more'),
    ]

    operations = [
        migrations.RunPython(consolidate_products, reverse_func),
    ]
