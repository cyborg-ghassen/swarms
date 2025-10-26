from typing import Any, Callable, Dict, Optional
import requests
from eth_account import Account
from .base import decode_x_payment_response, x402Client


class _SessionWithX402(requests.Session):
    def __init__(self, account: Account, payment_requirements_selector: Optional[Callable] = None):
        super().__init__()
        self.account = account
        self.payment_requirements_selector = payment_requirements_selector or x402Client.default_payment_requirements_selector

    def request(self, method: str, url: str, **kwargs):
        # For compatibility: do a normal request, and if the server returns a 402 with payment headers,
        # we could implement the x402 flow here. For now, just pass-through and return.
        resp = super().request(method, url, **kwargs)
        return resp


def x402_requests(account: Account, payment_requirements_selector: Optional[Callable] = None) -> _SessionWithX402:
    return _SessionWithX402(account=account, payment_requirements_selector=payment_requirements_selector)

