from django.db import migrations, models
import django.db.models.deletion
import django.contrib.postgres.search
import django.contrib.postgres.indexes


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_backfill_streaming_username'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('slug', models.SlugField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
                ('image', models.ImageField(blank=True, null=True, upload_to='categories/')),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name_plural': 'Categories',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Provider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('api_endpoint', models.URLField(blank=True, max_length=500)),
                ('api_token', models.BinaryField(blank=True, editable=False, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Provider',
                'verbose_name_plural': 'Providers',
            },
        ),
        migrations.RemoveIndex(
            model_name='product',
            name='api_product_categor_07b5d3_idx',
        ),
        migrations.RenameField(
            model_name='product',
            old_name='category',
            new_name='category_old',
        ),
        migrations.AlterField(
            model_name='product',
            name='category_old',
            field=models.CharField(
                blank=True,
                choices=[('IPTV', 'IPTV'), ('GAMING', 'Gaming'), ('STREAMING', 'Streaming')],
                default='IPTV',
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='products', to='api.category'),
        ),
        migrations.AddField(
            model_name='product',
            name='provider',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='products', to='api.provider'),
        ),
        migrations.AddField(
            model_name='product',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='products/originals/'),
        ),
        migrations.AddField(
            model_name='product',
            name='search_vector',
            field=django.contrib.postgres.search.SearchVectorField(null=True, editable=False),
        ),
        migrations.RemoveIndex(
            model_name='product',
            name='api_product_is_acti_b97ca3_idx',
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['is_active'], name='api_product_is_active_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['is_active', 'category'], name='api_product_cat_active_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=django.contrib.postgres.indexes.GinIndex(fields=['search_vector'], name='api_product_search_gin_idx'),
        ),
    ]
