import logging

logger = logging.getLogger('easypharma.middleware')

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        tenant_info = getattr(request, 'tenant', None)
        user_info = getattr(request, 'user', None)
        logger.info(
            "Request to view=%s method=%s path=%s user=%s tenant=%s",
            f"{view_func.__module__}.{view_func.__name__}",
            request.method,
            request.path,
            getattr(user_info, 'username', user_info),
            getattr(tenant_info, 'subdomain', tenant_info)
        )
        if request.method in ['POST', 'PATCH', 'PUT', 'DELETE']:
            try:
                body = request.body.decode('utf-8')
            except Exception:
                body = '<unreadable body>'
            logger.debug('Request body: %s', body[:2000])

    def process_exception(self, request, exception):
        tenant_info = getattr(request, 'tenant', None)
        user_info = getattr(request, 'user', None)
        logger.exception(
            "Exception in request path=%s user=%s tenant=%s error=%s",
            request.path,
            getattr(user_info, 'username', user_info),
            getattr(tenant_info, 'subdomain', tenant_info),
            exception,
        )
