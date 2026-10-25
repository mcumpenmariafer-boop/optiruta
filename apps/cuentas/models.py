from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuario del sistema con uno de los tres roles de negocio."""

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        SUPERVISOR = "SUPERVISOR", "Supervisor de despacho"
        CONDUCTOR = "CONDUCTOR", "Conductor"

    rol = models.CharField(max_length=12, choices=Rol.choices, default=Rol.CONDUCTOR)
    telefono = models.CharField(max_length=15, blank=True)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def es_admin(self):
        return self.rol == self.Rol.ADMIN or self.is_superuser

    @property
    def es_supervisor(self):
        return self.rol == self.Rol.SUPERVISOR

    @property
    def es_conductor(self):
        return self.rol == self.Rol.CONDUCTOR

    def __str__(self):
        return self.get_full_name() or self.username
