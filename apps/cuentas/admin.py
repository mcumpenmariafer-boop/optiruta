from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "rol", "is_active")
    list_filter = ("rol", "is_active")
    fieldsets = UserAdmin.fieldsets + (("OptiRuta", {"fields": ("rol", "telefono")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("OptiRuta", {"fields": ("rol", "telefono")}),)
