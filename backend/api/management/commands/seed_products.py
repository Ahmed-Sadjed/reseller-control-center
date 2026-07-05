from decimal import Decimal
from django.core.management.base import BaseCommand
from api.models import Category, Provider, Product, ProductVariant

# Your 13 IPTV product names
IPTV_PRODUCT_NAMES = [
    "Pro max",
    "Tivione",
    "Strong",
    "Neo",
    "Goldan ott",
    "Hot player",
    "Vip2",
    "Vip pagke",
    "Terx",
    "Km4k",
    "Ts4k",
    "V12 ott",
    "matic4k",
]

class Command(BaseCommand):
    help = 'Seed initial products (generic per category, or 13 IPTV products)'

    def add_arguments(self, parser):
        parser.add_argument('--category', type=str, help='Category slug to seed (e.g., iptv)')
        parser.add_argument(
            '--only-iptv',
            action='store_true',
            help='Only seed the 13 IPTV products (ignore other categories)',
        )

    def handle(self, *args, **options):
        provider = Provider.objects.filter(is_active=True).first()
        if not provider:
            self.stderr.write(self.style.ERROR('No active Provider found. Create one first.'))
            return

        categories = Category.objects.filter(is_active=True)
        if options['category']:
            categories = categories.filter(slug=options['category'])

        if options['only_iptv']:
            categories = categories.filter(slug='iptv')

        for cat in categories:
            # Special handling for IPTV category
            if cat.slug == 'iptv':
                self._seed_iptv_products(cat, provider)
                continue

            # Generic: one product per category (skip if products exist)
            existing = Product.objects.filter(category=cat).count()
            if existing > 0:
                self.stdout.write(f'Skipping {cat.name}: {existing} products exist')
                continue

            product = Product.objects.create(
                name=f'{cat.name} Subscription',
                category=cat,
                provider=provider,
                description=f'Standard {cat.name} subscription package',
                is_active=True,
            )

            durations = [
                (1, Decimal('9.99'), 100),
                (3, Decimal('24.99'), 101),
                (6, Decimal('44.99'), 102),
                (12, Decimal('79.99'), 103),
            ]

            for months, price, pack_id in durations:
                ProductVariant.objects.create(
                    product=product,
                    duration_months=months,
                    price_in_credits=price,
                    external_pack_id=pack_id,
                    is_active=True,
                )

            self.stdout.write(self.style.SUCCESS(
                f'Created {cat.name} with {len(durations)} variants'
            ))

    def _seed_iptv_products(self, category, provider):
        """Create all 13 IPTV products (each with default variants)."""
        existing = Product.objects.filter(category=category).count()
        if existing > 0:
            self.stdout.write(
                self.style.WARNING(f'Skipping IPTV products: {existing} already exist')
            )
            return

        for name in IPTV_PRODUCT_NAMES:
            product = Product.objects.create(
                name=name.strip(),
                category=category,
                provider=provider,
                description=f'{name.strip()} – premium IPTV subscription',
                is_active=True,
            )

            # Same variant structure as generic ones – you can adjust later
            durations = [
                (1, Decimal('9.99'), 200),
                (3, Decimal('24.99'), 201),
                (6, Decimal('44.99'), 202),
                (12, Decimal('79.99'), 203),
            ]
            for months, price, pack_id in durations:
                ProductVariant.objects.create(
                    product=product,
                    duration_months=months,
                    price_in_credits=price,
                    external_pack_id=pack_id,
                    is_active=True,
                )
            self.stdout.write(self.style.SUCCESS(f'Created: {name} ({len(durations)} variants)'))