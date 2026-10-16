import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_totp_auditlog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(choices=[('LOGIN', 'Inicio de sesión del personal'), ('LOGIN_BLOQUEADO', 'Cuenta bloqueada por intentos fallidos'), ('USUARIO_CREADO', 'Usuario creado'), ('USUARIO_ESTADO', 'Usuario activado o desactivado'), ('DOS_PASOS_ON', 'Verificación en dos pasos activada'), ('DOS_PASOS_OFF', 'Verificación en dos pasos quitada'), ('TICKET_ELIMINADO', 'Ticket eliminado'), ('RESPUESTA_CREADA', 'Respuesta del asistente creada'), ('RESPUESTA_EDITADA', 'Respuesta del asistente editada'), ('RESPUESTA_ELIMINADA', 'Respuesta del asistente eliminada'), ('DATOS_EXPORTADOS', 'Datos personales descargados'), ('CUENTA_ELIMINADA', 'Cuenta eliminada por su dueño'), ('FOTO_SUBIDA', 'Foto de trabajos subida'), ('FOTO_EDITADA', 'Foto de trabajos editada'), ('FOTO_ELIMINADA', 'Foto de trabajos eliminada')], max_length=30),
        ),
        migrations.CreateModel(
            name='WorkPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('segment', models.CharField(max_length=60)),
                ('image', models.ImageField(upload_to='trabajos/%Y/%m/')),
                ('width', models.PositiveIntegerField(blank=True, null=True)),
                ('height', models.PositiveIntegerField(blank=True, null=True)),
                ('caption', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
    ]
