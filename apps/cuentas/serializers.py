from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Usuario


class UsuarioSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()
    rol_display = serializers.CharField(source="get_rol_display", read_only=True)
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Usuario
        fields = [
            "id", "username", "first_name", "last_name", "nombre_completo",
            "email", "telefono", "rol", "rol_display", "is_active", "password",
        ]

    def get_nombre_completo(self, obj) -> str:
        return obj.get_full_name() or obj.username

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_telefono(self, value):
        if value and (not value.isdigit() or len(value) != 9 or not value.startswith("9")):
            raise serializers.ValidationError("El celular peruano (+51) debe tener 9 dígitos y empezar con 9.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "La contraseña es obligatoria."})
        usuario = Usuario(**validated_data)
        usuario.set_password(password)
        usuario.save()
        return usuario

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LoginSerializer(TokenObtainPairSerializer):
    """Devuelve los tokens JWT junto con los datos del usuario y su rol."""

    default_error_messages = {
        "no_active_account": "Usuario o contraseña incorrectos."
    }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["rol"] = "ADMIN" if user.es_admin else user.rol
        token["nombre"] = user.get_full_name() or user.username
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        usuario = UsuarioSerializer(self.user).data
        if self.user.es_admin:
            usuario["rol"] = "ADMIN"
        data["usuario"] = usuario
        return data
