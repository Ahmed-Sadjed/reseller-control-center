import urllib.parse

from django.db import migrations


def backfill_streaming_username(apps, schema_editor):
    Credential = apps.get_model('api', 'Credential')
    for cred in Credential.objects.filter(streaming_username__isnull=True):
        if cred.dns_domain:
            try:
                parsed = urllib.parse.urlparse(cred.dns_domain)
                params = urllib.parse.parse_qs(parsed.query)
                streaming_username = params.get('username', [''])[0]
                if streaming_username:
                    cred.streaming_username = streaming_username
                    cred.save()
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_credential_streaming_username'),
    ]

    operations = [
        migrations.RunPython(backfill_streaming_username, migrations.RunPython.noop),
    ]
