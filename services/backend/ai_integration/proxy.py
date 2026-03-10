"""
Generic AI proxy helper.

Forwards requests from Django to the internal AI service at AI_BASE_INTERNAL,
preserving method, headers, query params, body, and streaming responses.
"""
import logging
import os

import requests as http_client
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse

logger = logging.getLogger(__name__)

AI_BASE = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
_CONNECT_TIMEOUT = 5   # fast-fail if AI service is unreachable
_READ_TIMEOUT = 30     # seconds for non-streaming reads
_STREAM_TIMEOUT = 120
_CHUNK = 8192

# Headers we never forward downstream
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "host",
})


def _build_url(path: str) -> str:
    """Join AI_BASE + path, avoiding double slashes."""
    base = AI_BASE.rstrip("/")
    path = path.lstrip("/")
    return f"{base}/{path}"


def _filtered_headers(request) -> dict:
    """Extract safe request headers to forward."""
    headers = {}
    for key, val in request.META.items():
        if key.startswith("HTTP_"):
            name = key[5:].replace("_", "-").lower()
            if name not in _HOP_BY_HOP:
                headers[name] = val
    ct = request.META.get("CONTENT_TYPE")
    if ct:
        headers["content-type"] = ct
    return headers


def proxy_request(
    request,
    ai_path: str,
    *,
    stream: bool = False,
    override_method: str | None = None,
):
    """
    Forward a Django request to the AI service and return the response.

    Parameters
    ----------
    request : HttpRequest
    ai_path : str          – path on the AI service (e.g. "/cameras")
    stream  : bool         – if True, return a streaming response (for binary)
    override_method : str  – force a different HTTP method
    """
    url = _build_url(ai_path)
    method = (override_method or request.method).upper()
    headers = _filtered_headers(request)
    params = request.GET.dict()

    timeout = (_CONNECT_TIMEOUT, _STREAM_TIMEOUT) if stream else (_CONNECT_TIMEOUT, _READ_TIMEOUT)

    try:
        # Handle multipart uploads
        content_type = headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            # Reconstruct multipart: forward Django's FILES + POST data
            files = []
            for field_name, file_list in request.FILES.lists():
                for f in file_list:
                    files.append((field_name, (f.name, f, f.content_type)))
            data = request.POST.dict()
            # Don't forward content-type for multipart — let requests set it
            headers.pop("content-type", None)
            resp = http_client.request(
                method,
                url,
                params=params,
                data=data,
                files=files,
                headers=headers,
                stream=stream,
                timeout=timeout,
            )
        else:
            resp = http_client.request(
                method,
                url,
                params=params,
                data=request.body if method in ("POST", "PUT", "PATCH") else None,
                headers=headers,
                stream=stream,
                timeout=timeout,
            )

        if stream:
            django_resp = StreamingHttpResponse(
                resp.iter_content(_CHUNK),
                status=resp.status_code,
                content_type=resp.headers.get("content-type", "application/octet-stream"),
            )
            # Prevent caching of live frames / evidence
            django_resp["Cache-Control"] = "no-store"
            # Forward content-disposition if present (for downloads)
            cd = resp.headers.get("content-disposition")
            if cd:
                django_resp["Content-Disposition"] = cd
            return django_resp

        # Non-streaming: return as-is with correct content type
        ct = resp.headers.get("content-type", "application/json")
        return HttpResponse(
            content=resp.content,
            status=resp.status_code,
            content_type=ct,
        )

    except http_client.Timeout:
        logger.error("AI proxy timeout: %s %s", method, url)
        return JsonResponse(
            {"error": "AI service timeout"},
            status=504,
        )
    except http_client.ConnectionError:
        logger.error("AI proxy connection error: %s %s", method, url)
        return JsonResponse(
            {"error": "AI service unavailable"},
            status=502,
        )
    except Exception:
        logger.exception("AI proxy unexpected error: %s %s", method, url)
        return JsonResponse(
            {"error": "Internal proxy error"},
            status=500,
        )
