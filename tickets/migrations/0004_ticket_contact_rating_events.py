import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0003_ticket_image_ticket_closed_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticket',
            name='status',
            field=models.CharField(choices=[('ABIERTO', 'Abierto'), ('ASIGNADO', 'Asignado'), ('EN_PROCESO', 'En proceso'), ('CERRADO', 'Cerrado'), ('CANCELADO', 'Cancelado')], default='ABIERTO', max_length=20),
        ),
        migrations.AddField(
            model_name='ticket',
            name='phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='ticket',
            name='address',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='ticket',
            name='rating',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='rating_comment',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.CreateModel(
            name='TicketEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('CREADO', 'Creado'), ('ASIGNADO', 'Asignado'), ('ESTADO', 'Cambio de estado'), ('CATEGORIA', 'Cambio de categoría'), ('REABIERTO', 'Reabierto'), ('CANCELADO', 'Cancelado'), ('CALIFICADO', 'Calificado')], max_length=12)),
                ('detail', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='tickets.ticket')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
