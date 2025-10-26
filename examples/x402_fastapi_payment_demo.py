#!/usr/bin/env python3
"""
FastAPI demo that requires payments for specific routes using x402-style middleware.

This file mirrors the reference you provided but is runnable even if `x402` isn't
installed: it will attempt to import the real types and helpers and otherwise provide
small local stubs so you can run and test the endpoints locally.

Environment variables (create a .env or set in your shell):
  ADDRESS           - receiving address for payments (used in example middleware)
  FACILITATOR_URL   - URL of the payment facilitator (mock or real)

Run locally (example):
  set FACILITATOR_URL=http://127.0.0.1:8000
  set ADDRESS=0x0123456789abcdef0123456789abcdef01234567
  python examples\x402_fastapi_payment_demo.py

Then visit:
  http://127.0.0.1:4021/weather
  http://127.0.0.1:4021/premium/content

The middleware will log when a payment check would occur. If you have the real
`x402` package available, the script will use it instead of the stubs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()

ADDRESS = os.getenv("ADDRESS")
FACILITATOR_URL = os.getenv("FACILITATOR_URL")

if not ADDRESS or not FACILITATOR_URL:
    raise ValueError("Missing required environment variables: ADDRESS and FACILITATOR_URL must be set")

# Try to import real x402 helpers; if unavailable, provide lightweight stubs so the demo runs.
try:
    from x402.fastapi.middleware import require_payment
    from x402.facilitator import FacilitatorConfig
    from x402.types import EIP712Domain, TokenAmount, TokenAsset
    REAL_X402 = True
except Exception:
    REAL_X402 = False

    @dataclass
    class FacilitatorConfig:
        url: str

    @dataclass
    class EIP712Domain:
        name: str
        version: Optional[str] = None

    @dataclass
    class TokenAsset:
        address: str
        decimals: int = 18
        eip712: Optional[EIP712Domain] = None

    @dataclass
    class TokenAmount:
        amount: str
        asset: TokenAsset

    def _match_path(request_path: str, pattern: str) -> bool:
        # support patterns like '/premium/*' or exact '/weather'
        if pattern.endswith("/*"):
            return request_path.startswith(pattern[:-1])
        return request_path == pattern

    def require_payment(path: str, price: Any, pay_to_address: str, network: str, facilitator_config: FacilitatorConfig):
        """
        Returns a middleware function for FastAPI that enforces a (stubbed) payment check.

        In this demo stub, the middleware logs that payment would be required. If the request
        includes a header `X-MOCK-PAYED: true` then the middleware allows the request; otherwise it
        returns a 402-like JSON response indicating payment required.
        """

        async def middleware(request: Request, call_next):
            # Only enforce for matching paths
            if _match_path(request.url.path, path):
                # Simple mock behavior: allow if client sets X-MOCK-PAYED: true header
                paid_header = request.headers.get("x-mock-payed", "false").lower()
                if paid_header in ("1", "true", "yes"):
                    # proceed to handler
                    return await call_next(request)
                # return a payment-required response (JSON)
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "payment_required",
                        "message": "This endpoint requires payment. In the real integration the x402 facilitator would verify and settle.",
                        "required_price": str(price),
                        "pay_to": pay_to_address,
                        "network": network,
                        "facilitator": facilitator_config.url,
                    },
                )
            return await call_next(request)

        return middleware

# Build facilitator config and app
facilitator_config = FacilitatorConfig(url=FACILITATOR_URL)
app = FastAPI()

# Apply middleware for /weather
app.middleware("http")(
    require_payment(
        path="/weather",
        price="$0.001",
        pay_to_address=ADDRESS,
        network="base-sepolia",
        facilitator_config=facilitator_config,
    )
)

# Apply middleware for /premium/* (example uses TokenAmount)
app.middleware("http")(
    require_payment(
        path="/premium/*",
        price=TokenAmount(
            amount="10000",
            asset=TokenAsset(
                address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                decimals=6,
                eip712=EIP712Domain(name="USDC", version="2") if hasattr(globals().get("EIP712Domain"), "__name__") else None,
            ),
        ),
        pay_to_address=ADDRESS,
        network="base-sepolia",
        facilitator_config=facilitator_config,
    )
)


@app.get("/weather")
async def get_weather() -> Dict[str, Any]:
    return {"report": {"weather": "sunny", "temperature": 70}}


@app.get("/premium/content")
async def get_premium_content() -> Dict[str, Any]:
    return {"content": "This is premium content"}


if __name__ == "__main__":
    import uvicorn

    print("Running x402 FastAPI payment demo")
    if REAL_X402:
        print("Using real x402 package for middleware")
    else:
        print("x402 package not found; running with stubbed middleware (local mock behavior)")
    uvicorn.run(app, host="0.0.0.0", port=4021)

