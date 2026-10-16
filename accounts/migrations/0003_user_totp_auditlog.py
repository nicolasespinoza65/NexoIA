import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_phone_address_email_verified'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='totp_secret',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='user',
            name='totp_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='totp_last_step',
            field=models.BigIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('LOGIN', 'Inicio de sesión del personal'), ('LOGIN_BLOQUEADO', 'Cuenta bloqueada por intentos fallidos'), ('USUARIO_CREADO', 'Usuario creado'), ('USUARIO_ESTADO', 'Usuario activado o desactivado'), ('DOS_PASOS_ON', 'Verificación en dos pasos activada'), ('DOS_PASOS_OFF', 'Verificación en dos pasos quitada'), ('TICKET_ELIMINADO', 'Ticket eliminado'), ('RESPUESTA_CREADA', 'Respuesta del asistente creada'), ('RESPUESTA_EDITADA', 'Respuesta del asistente editada'), ('RESPUESTA_ELIMINADA', 'Respuesta del asistente eliminada'), ('DATOS_EXPORTADOS', 'Datos personales descargados'), ('CUENTA_ELIMINADA', 'Cuenta eliminada por su dueño')], max_length=30)),
                ('target', models.CharField(blank=True, max_length=120)),
                ('detail', models.CharField(blank=True, max_length=255)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
    ]
