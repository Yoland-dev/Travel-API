from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.exceptions import custom_exception_handler
from core.testing import BaseAPITest, pdf_file
from core.validators import validate_document_type, validate_file_size, validate_image_type


class ValidatorTests(SimpleTestCase):
    def test_file_size_limit(self):
        validate_file_size(pdf_file())
        with self.assertRaises(ValidationError):
            validate_file_size(pdf_file(size=6 * 1024 * 1024))

    def test_image_type(self):
        validate_image_type(SimpleUploadedFile("a.PNG", b"x"))
        with self.assertRaises(ValidationError):
            validate_image_type(SimpleUploadedFile("a.gif", b"x"))

    def test_document_type_and_mime(self):
        validate_document_type(pdf_file())
        with self.assertRaises(ValidationError):
            validate_document_type(SimpleUploadedFile("a.pdf", b"x", content_type="text/html"))
        with self.assertRaises(ValidationError):
            validate_document_type(SimpleUploadedFile("a.exe", b"x"))


class ExceptionHandlerTests(SimpleTestCase):
    def test_protected_error_maps_to_409(self):
        response = custom_exception_handler(ProtectedError("blocked", []), {})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_integrity_error_maps_to_400(self):
        self.assertEqual(custom_exception_handler(IntegrityError("dup"), {}).status_code, 400)

    def test_unknown_exception_is_not_swallowed(self):
        self.assertIsNone(custom_exception_handler(RuntimeError("boom"), {}))


class ErrorResponseTests(BaseAPITest):
    def test_404_has_status_code_field(self):
        response = self.client.get("/api/v1/itineraries/99999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["status_code"], 404)

    def test_401_and_403_shapes(self):
        anon = APIClient().get("/api/v1/itineraries/")
        self.assertEqual((anon.status_code, anon.data["status_code"]), (401, 401))
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        forbidden = self.client.delete(f"/api/v1/itineraries/{self.itinerary.id}/")
        self.assertEqual(forbidden.status_code, 403)


class DocsTests(APITestCase):
    def test_schema_swagger_and_redoc_are_served(self):
        for url in ("/api/schema/", "/api/docs/", "/api/redoc/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_schema_lists_key_endpoints(self):
        content = self.client.get("/api/schema/").content.decode()
        for path in ("/api/v1/itineraries/", "/api/v1/accounts/login/", "/api/v1/bookings/bulk-update/"):
            self.assertIn(path, content)
