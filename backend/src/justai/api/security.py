"""Security headers for every HTTP response (pure ASGI, safe for streaming responses)."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Mantine injects <style> elements, hence 'unsafe-inline' for styles only. Scripts
# come exclusively from the bundled assets. Display images may be https URLs.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' ws: wss:; "
       "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self'")

_STATIC_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The interactive API docs load Swagger UI from a CDN; everything else is strict.
        with_csp = not str(scope.get("path", "")).startswith("/api/docs")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in _STATIC_HEADERS if k not in present]
                if with_csp and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
