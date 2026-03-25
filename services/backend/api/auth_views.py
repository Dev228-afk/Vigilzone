from rest_framework import serializers, views, status
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction

from .models import Tenant, Membership

User = get_user_model()

# Feature flag — when True a personal Tenant + owner Membership are created
# alongside the new user so they never get stuck on "Select community".
# Disabled to allow new users to select from pending community invites instead.
AUTO_CREATE_TENANT_ON_REGISTER = getattr(
    settings, "AUTO_CREATE_TENANT_ON_REGISTER", False
)


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_email(self, value):
        # Email uniqueness is not enforced in Django by default
        # But we can add validation if needed
        return value

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )


class RegisterView(views.APIView):
    permission_classes = []
    authentication_classes = []

    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            tenant_payload = None
            if AUTO_CREATE_TENANT_ON_REGISTER:
                tenant_name = f"{user.username}'s Community"
                tenant = Tenant.objects.create(name=tenant_name)
                Membership.objects.create(
                    user=user, tenant=tenant, role=Membership.Role.OWNER,
                )
                tenant_payload = {"id": tenant.id, "name": tenant.name}

            return Response(
                {
                    "message": "User registered successfully",
                    "tenant": tenant_payload,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
