from http import HTTPStatus

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

User = get_user_model()


class CustomBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None):
        if not username or not password:
            return None

        try:
            login_response = requests.post(
                settings.AUTH_API_LOGIN_URL,
                json={"login": username, "password": password},
                timeout=settings.AUTH_API_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return None

        if login_response.status_code != HTTPStatus.OK:
            return None

        payload = login_response.json()
        access_token = payload.get("access_token")
        if not access_token:
            return None

        try:
            me_response = requests.get(
                settings.AUTH_API_ME_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=settings.AUTH_API_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return None

        if me_response.status_code != HTTPStatus.OK:
            return None

        me = me_response.json()
        user_roles = me.get("roles", [])
        is_superuser = bool(me.get("is_superuser"))
        is_admin = is_superuser or ("admin" in user_roles)
        if not is_admin:
            return None

        user_id = me.get("id")
        login = me.get("login")
        if not user_id or not login:
            return None

        user, _ = User.objects.get_or_create(
            id=user_id,
            defaults={"login": login},
        )
        user.login = login
        user.is_active = bool(me.get("is_active", True))
        user.is_staff = is_admin
        user.is_superuser = is_superuser
        user.first_name = me.get("first_name", "") or ""
        user.last_name = me.get("last_name", "") or ""
        user.save(update_fields=["login", "is_active", "is_staff", "is_superuser", "first_name", "last_name", "updated_at"])
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
