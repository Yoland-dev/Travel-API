from datetime import timedelta

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.testing import PASSWORD, make_user

from .models import SavedSearch, User
from .serializers import UserRegistrationSerializer, UserSerializer

BASE = "/api/v1/accounts"


class UserModelTests(TestCase):
    def test_str_and_full_name(self):
        user = make_user("amina", first_name="Amina", last_name="Dlamini")
        self.assertEqual(str(user), "amina")
        self.assertEqual(user.full_name, "Amina Dlamini")

    def test_full_name_falls_back_to_username(self):
        self.assertEqual(make_user("solo").full_name, "solo")

    def test_future_birth_date_is_invalid(self):
        user = make_user("future")
        user.date_of_birth = timezone.now().date() + timedelta(days=5)
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_saved_search_str(self):
        user = make_user("s")
        search = SavedSearch.objects.create(user=user, name="Beaches", search_type="trip")
        self.assertEqual(str(search), "Beaches (trip)")


class UserSerializerTests(TestCase):
    def test_registration_password_mismatch(self):
        s = UserRegistrationSerializer(data={
            "username": "a", "email": "a@x.com", "password": PASSWORD, "password_confirm": "different"})
        self.assertFalse(s.is_valid())
        self.assertIn("password_confirm", s.errors)

    def test_registration_duplicate_email_case_insensitive(self):
        make_user("first", email="dup@example.com")
        s = UserRegistrationSerializer(data={
            "username": "b", "email": "DUP@example.com", "password": PASSWORD, "password_confirm": PASSWORD})
        self.assertFalse(s.is_valid())
        self.assertIn("email", s.errors)

    def test_password_is_write_only(self):
        user = make_user("w")
        self.assertNotIn("password", UserSerializer(user).data)

    def test_travel_preferences_validation(self):
        user = make_user("p")
        s = UserSerializer(user, data={"travel_preferences": {"bogus": 1}}, partial=True)
        self.assertFalse(s.is_valid())
        s = UserSerializer(user, data={"travel_preferences": {"categories": "beach"}}, partial=True)
        self.assertFalse(s.is_valid())
        s = UserSerializer(user, data={"travel_preferences": {"categories": ["beach"]}}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)


class AuthAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_user("tester", email="tester@example.com")

    def _register(self, **overrides):
        data = {"username": "newbie", "email": "newbie@example.com", "password": PASSWORD,
                "password_confirm": PASSWORD}
        data.update(overrides)
        return self.client.post(f"{BASE}/register/", data)

    def test_register_returns_tokens(self):
        response = self._register()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data["tokens"])
        self.assertNotIn("password", response.data["user"])
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_register_weak_password_rejected(self):
        response = self._register(password="12345678", password_confirm="12345678")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_with_username(self):
        response = self.client.post(f"{BASE}/login/", {"username": "tester", "password": PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", response.data["tokens"])

    def test_login_with_email(self):
        response = self.client.post(f"{BASE}/login/", {"username": "tester@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_wrong_password_401(self):
        response = self.client.post(f"{BASE}/login/", {"username": "tester", "password": "nope"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_fields_400(self):
        response = self.client.post(f"{BASE}/login/", {"username": "tester"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_token_refresh_and_use(self):
        tokens = self.client.post(f"{BASE}/login/", {"username": "tester", "password": PASSWORD}).data["tokens"]
        refreshed = self.client.post(f"{BASE}/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(refreshed.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.data['access']}")
        self.assertEqual(self.client.get(f"{BASE}/profile/").status_code, status.HTTP_200_OK)

    def test_logout_blacklists_refresh_token(self):
        tokens = self.client.post(f"{BASE}/login/", {"username": "tester", "password": PASSWORD}).data["tokens"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.post(f"{BASE}/logout/", {"refresh": tokens["refresh"]}).status_code, 205)
        again = self.client.post(f"{BASE}/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(again.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_invalid_token_400(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(f"{BASE}/logout/", {"refresh": "garbage"}).status_code, 400)

    def test_profile_requires_authentication(self):
        self.assertEqual(self.client.get(f"{BASE}/profile/").status_code, status.HTTP_401_UNAUTHORIZED)


class ProfileAPITests(APITestCase):
    def setUp(self):
        self.user = make_user("profile")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_get_profile(self):
        response = self.client.get(f"{BASE}/profile/")
        self.assertEqual(response.data["username"], "profile")
        self.assertEqual(response.data["owned_trips_count"], 0)

    def test_patch_profile(self):
        response = self.client.patch(f"{BASE}/profile/", {"bio": "Hiker", "travel_preferences": {"categories": ["mountain"]}},
                                     format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, "Hiker")

    def test_username_is_read_only(self):
        self.client.patch(f"{BASE}/profile/", {"username": "hacked"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profile")

    def test_email_must_stay_unique(self):
        make_user("taken", email="taken@example.com")
        response = self.client.patch(f"{BASE}/profile/", {"email": "taken@example.com"})
        self.assertEqual(response.status_code, 400)

    def test_change_password(self):
        response = self.client.post(f"{BASE}/password/change/", {"old_password": PASSWORD, "new_password": "BrandNew#Pass9"})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew#Pass9"))

    def test_change_password_wrong_old(self):
        response = self.client.post(f"{BASE}/password/change/", {"old_password": "bad", "new_password": "BrandNew#Pass9"})
        self.assertEqual(response.status_code, 400)


class PasswordResetTests(APITestCase):
    def setUp(self):
        self.user = make_user("reset", email="reset@example.com")
        self.client = APIClient()

    def test_request_sends_email(self):
        response = self.client.post(f"{BASE}/password/reset/", {"email": "reset@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_request_unknown_email_does_not_reveal(self):
        response = self.client.post(f"{BASE}/password/reset/", {"email": "ghost@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_sets_new_password(self):
        payload = {"uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
                   "token": default_token_generator.make_token(self.user), "new_password": "Fresh#Pass987"}
        self.assertEqual(self.client.post(f"{BASE}/password/reset/confirm/", payload).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Fresh#Pass987"))

    def test_confirm_rejects_bad_token(self):
        payload = {"uid": urlsafe_base64_encode(force_bytes(self.user.pk)), "token": "bad-token",
                   "new_password": "Fresh#Pass987"}
        self.assertEqual(self.client.post(f"{BASE}/password/reset/confirm/", payload).status_code, 400)

    def test_confirm_rejects_bad_uid(self):
        payload = {"uid": "zzzz", "token": "x", "new_password": "Fresh#Pass987"}
        self.assertEqual(self.client.post(f"{BASE}/password/reset/confirm/", payload).status_code, 400)


class SavedSearchAPITests(APITestCase):
    def setUp(self):
        self.user = make_user("saver")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_crud_and_isolation(self):
        payload = {"name": "Beaches", "search_type": "destination", "query_params": {"category": "beach"}}
        created = self.client.post("/api/v1/saved-searches/", payload, format="json")
        self.assertEqual(created.status_code, 201)
        sid = created.data["id"]
        self.assertEqual(self.client.patch(f"/api/v1/saved-searches/{sid}/", {"name": "Sun"}).data["name"], "Sun")
        self.assertEqual(self.client.get("/api/v1/saved-searches/", {"search_type": "destination"}).data["count"], 1)
        self.client.force_authenticate(make_user("nosy"))
        self.assertEqual(self.client.get("/api/v1/saved-searches/").data["count"], 0)
        self.assertEqual(self.client.delete(f"/api/v1/saved-searches/{sid}/").status_code, 404)

    def test_query_params_must_be_object(self):
        response = self.client.post("/api/v1/saved-searches/", {"name": "x", "search_type": "trip", "query_params": [1]},
                                    format="json")
        self.assertEqual(response.status_code, 400)
