from rest_framework.pagination import PageNumberPagination


class Paginacion(PageNumberPagination):
    """Paginación estándar (Tema 7.3): ?page=2&page_size=50 (máximo 200)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200
