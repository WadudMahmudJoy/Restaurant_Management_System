"""Middleware: request timing header used by the dashboard's health strip."""
from __future__ import annotations

import time


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed = (time.perf_counter() - started) * 1000
        response["X-Response-Time"] = f"{elapsed:.1f}ms"
        return response
