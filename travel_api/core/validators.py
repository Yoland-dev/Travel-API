"""Reusable upload validators (size and type)."""
import os

from django.core.exceptions import ValidationError

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
DOCUMENT_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}


def validate_file_size(file):
    """Reject files larger than MAX_UPLOAD_SIZE."""
    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError(f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")


def validate_image_type(file):
    """Only JPEG and PNG images are accepted."""
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Unsupported image type. Use JPG or PNG.")


def validate_document_type(file):
    """PDFs and JPG/PNG photos are accepted (extension and, when known, MIME type)."""
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in DOCUMENT_EXTENSIONS:
        raise ValidationError("Unsupported file type. Use PDF, JPG or PNG.")
    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in DOCUMENT_MIME_TYPES:
        raise ValidationError("File content type does not match an allowed type.")
