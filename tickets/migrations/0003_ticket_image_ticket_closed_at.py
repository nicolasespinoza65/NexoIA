from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0002_ticket_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='image',
            field=models.ImageField(blank=True, upload_to='tickets/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='ticket',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
