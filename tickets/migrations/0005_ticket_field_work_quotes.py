import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0004_ticket_contact_rating_events'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='closing_note',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='ticket',
            name='visit_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='visit_note',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='ticket',
            name='visit_reminded',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='ticketevent',
            name='kind',
            field=models.CharField(choices=[('CREADO', 'Creado'), ('ASIGNADO', 'Asignado'), ('ESTADO', 'Cambio de estado'), ('CATEGORIA', 'Cambio de categoría'), ('REABIERTO', 'Reabierto'), ('CANCELADO', 'Cancelado'), ('CALIFICADO', 'Calificado'), ('COTIZACION', 'Cotización enviada'), ('RESPUESTA', 'Cotización respondida'), ('VISITA', 'Visita agendada'), ('PRIORIDAD', 'Cambio de prioridad')], max_length=12),
        ),
        migrations.CreateModel(
            name='Quote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('detail', models.TextField(max_length=1500)),
                ('amount', models.PositiveIntegerField()),
                ('valid_until', models.DateField()),
                ('status', models.CharField(choices=[('PENDIENTE', 'Pendiente de respuesta'), ('ACEPTADA', 'Aceptada'), ('RECHAZADA', 'Rechazada'), ('REEMPLAZADA', 'Reemplazada por otra')], default='PENDIENTE', max_length=12)),
                ('response_comment', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quotes', to='tickets.ticket')),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='TicketPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='tickets/work/%Y/%m/')),
                ('caption', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ticket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='tickets.ticket')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
