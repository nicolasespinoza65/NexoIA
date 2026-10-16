"""Crea usuarios de prueba (uno por rol) si todavía no existen.

Uso normal:      python manage.py seed_users          -> contraseñas aleatorias (se muestran una sola vez)
Solo para local: python manage.py seed_users --demo   -> contraseñas simples (admin123, mod123...)
Nunca uses --demo en un servidor accesible desde internet."""
import secrets

from django.core.management.base import BaseCommand
from accounts.models import User

SEED = [
    ("admin", "admin@ssdp.cl", "admin123", User.Role.ADMIN, "Administrador"),
    ("mod", "mod@ssdp.cl", "mod123", User.Role.MODERADOR, "Moderador"),
    ("trabajador", "trabajador@ssdp.cl", "trab123", User.Role.TRABAJADOR, "Trabajador"),
    ("cliente", "cliente@ssdp.cl", "cli123", User.Role.CLIENTE, "Cliente"),
]


class Command(BaseCommand):
    help = "Crea los 4 usuarios de prueba (uno por rol)"

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Usa contraseñas simples (solo para desarrollo local)")

    def handle(self, *args, **options):
        for username, email, demo_password, role, first_name in SEED:
            if User.objects.filter(username=username).exists():
                self.stdout.write(f"Ya existe: {username}")
                continue
            password = demo_password if options["demo"] else secrets.token_urlsafe(9)
            User.objects.create_user(
                username=username, email=email, password=password, role=role, first_name=first_name,
                email_verified=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Creado: {username} ({role}) contraseña: {password}"))
        if not options["demo"]:
            self.stdout.write("Anota las contraseñas: no se vuelven a mostrar. Para cambiar una: python manage.py changepassword USUARIO")
