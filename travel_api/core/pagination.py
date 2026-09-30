"""Custom pagination classes."""
from rest_framework.pagination import PageNumberPagination


class SmallPagination(PageNumberPagination):
    """Compact pages for search-style endpoints (5 per page, client adjustable up to 50)."""

    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 50
