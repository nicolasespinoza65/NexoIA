from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='category',
            field=models.CharField(choices=[('INSTALACION', 'Instalación eléctrica'), ('MANTENCION', 'Mantención o reparación'), ('COTIZACION', 'Cotización'), ('EMERGENCIA', 'Emergencia'), ('RECLAMO', 'Reclamo'), ('CONSULTA', 'Consulta general'), ('OTRO', 'Otro')], default='OTRO', max_length=20),
        ),
    ]
