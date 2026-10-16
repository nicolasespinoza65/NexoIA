from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0002_faqentry'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='reviewed',
            field=models.BooleanField(default=False),
        ),
    ]
