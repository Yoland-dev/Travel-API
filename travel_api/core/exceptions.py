"""Consistent error handling for the whole API."""
from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """Wrap DRF's handler: add status_code and map DB errors to clean responses."""
    response = exception_handler(exc, context)
    if response is None:
        if isinstance(exc, ProtectedError):
            return Response(
                {"detail": "This object is referenced by other records and cannot be deleted.",
                 "status_code": status.HTTP_409_CONFLICT},
                status=status.HTTP_409_CONFLICT,
            )
        if isinstance(exc, IntegrityError):
            return Response(
                {"detail": "Database integrity error (duplicate or invalid reference).",
                 "status_code": status.HTTP_400_BAD_REQUEST},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None
    if isinstance(response.data, dict):
        response.data["status_code"] = response.status_code
    return response
