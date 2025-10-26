from typing import Any, Callable, Dict, Optional
from fastapi import Request, Response
from starlette.responses import JSONResponse


def require_payment(path: str, price: Any, pay_to_address: str, network: str, facilitator_config: Any):
    """Return a FastAPI middleware function that enforces a mock payment check.

    This compatibility implementation is intentionally simple: it checks for a header
    `X-MOCK-PAYED: true` to allow access. In production you'd call the facilitator to verify.
    """

    def _match(request_path: str, pattern: str) -> bool:
        if pattern.endswith("/*"):
            return request_path.startswith(pattern[:-1])
        return request_path == pattern

    async def middleware(request: Request, call_next: Callable):
        if _match(request.url.path, path):
            paid_header = request.headers.get("x-mock-payed", "false").lower()
            if paid_header in ("1", "true", "yes"):
                return await call_next(request)
            return JSONResponse(status_code=402, content={
                "error": "payment_required",
                "required_price": str(price),
                "pay_to": pay_to_address,
                "network": network,
                "facilitator": getattr(facilitator_config, "url", None),
            })
        return await call_next(request)

    return middleware

