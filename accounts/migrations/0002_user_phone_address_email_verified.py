from django.db import migrations, models


def mark_existing_users_verified(apps, schema_editor):
    """Quienes ya tenían cuenta antes de esta versión quedan con el correo verificado."""
    User = apps.get_model("accounts", "User")
    User.objects.update(email_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='user',
            name='address',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='user',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_users_verified, migrations.RunPython.noop),
    ]
