import re
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from api.models import Category, Provider, Product, ProductVariant
from api.providers import get_adapter_for_provider

DURATION_MAP = {
    ('months', 1): Product.Duration.ONE_MONTH,
    ('months', 3): Product.Duration.THREE_MONTHS,
    ('months', 6): Product.Duration.SIX_MONTHS,
    ('months', 12): Product.Duration.TWELVE_MONTHS,
    ('days', 365): Product.Duration.TWELVE_MONTHS,
    ('hours', 6): Product.Duration.TRIAL_6H,
    ('hours', 12): Product.Duration.TRIAL_12H,
    ('hours', 24): Product.Duration.TRIAL_24H,
}

def extract_category_name(package_name: str) -> str:
    match = re.match(r'^(.+?)\s+\d+\s+(MONTH|HOUR|DAY)', package_name, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return 'Redfoxx'

def upsert_package(provider, pkg: dict):
    name = pkg.get('name', '')
    pack_id = pkg.get('id')
    credits = pkg.get('credits', 0)
    duration = pkg.get('duration')
    duration_unit = pkg.get('duration_unit', '')
    is_trial = pkg.get('is_trial', False)

    if not name or not pack_id:
        return

    category_name = extract_category_name(name)
    category_slug = re.sub(r'[^a-z0-9]+', '-', category_name.lower()).strip('-')
    category, _ = Category.objects.get_or_create(
        slug=category_slug,
        defaults={
            'name': category_name,
            'description': f'Redfoxx packages - {category_name}',
            'is_active': True,
        },
    )

    product, created = Product.objects.get_or_create(
        provider=provider,
        name=name,
        defaults={
            'category': category,
            'description': f'Redfoxx package: {name}',
            'is_active': True,
        },
    )
    if not created and product.category_id != category.id:
        product.category = category
        product.save(update_fields=['category'])

    duration_key = (duration_unit, duration)
    duration_months = DURATION_MAP.get(duration_key)

    variant, variant_created = ProductVariant.objects.get_or_create(
        product=product,
        external_pack_id=pack_id,
        duration_months=duration_months,
        defaults={
            'price_in_credits': Decimal('0'),
            'is_lifetime': False,
            'is_active': True,
        },
    )
    if not variant_created:
        if variant.price_in_credits == 0 and credits > 0:
            pass
        if not variant.is_active:
            variant.is_active = True
            variant.save(update_fields=['is_active'])

    return product, variant, created or variant_created


class Command(BaseCommand):
    help = 'Sync packages from Redfoxx API into Products and Variants'

    def add_arguments(self, parser):
        parser.add_argument('--provider-id', type=int, help='Provider ID to sync (auto-detects first redfoxx provider if omitted)')

    def handle(self, *args, **options):
        provider_id = options.get('provider_id')
        if provider_id:
            provider = Provider.objects.filter(id=provider_id, adapter_key='redfoxx').first()
            if not provider:
                raise CommandError(f"No Redfoxx provider found with id={provider_id}")
        else:
            provider = Provider.objects.filter(adapter_key='redfoxx', is_active=True).first()
            if not provider:
                raise CommandError("No active Redfoxx provider found. Create one via admin first.")

        adapter = get_adapter_for_provider(provider)
        if not hasattr(adapter, 'get_packages'):
            raise CommandError("Adapter does not support get_packages")

        self.stdout.write(f"Fetching packages from Redfoxx ({provider.name})...")
        packages = adapter.get_packages()

        if not packages:
            self.stdout.write(self.style.WARNING("No packages returned from API"))
            return

        synced = 0
        skipped = 0
        for pkg in packages:
            result = upsert_package(provider, pkg)
            if result:
                product, variant, is_new = result
                action = "Created" if is_new else "Updated"
                self.stdout.write(f"  {action}: {product.name} (pack_id={pkg['id']}, credits={pkg.get('credits')})")
                synced += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f"Sync complete: {synced} products synced, {skipped} skipped"))
