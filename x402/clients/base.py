import json
from typing import Any, Dict, Optional


def decode_x_payment_response(header_value: str) -> Dict[str, Any]:
    # simple decode: try JSON, otherwise return raw
    try:
        return json.loads(header_value)
    except Exception:
        return {"transaction": header_value}


class x402Client:
    @staticmethod
    def default_payment_requirements_selector(accepts: Any, network_filter: Optional[str] = None, scheme_filter: Optional[str] = None, max_value: Optional[float] = None):
        # Very small selector: return the first that matches the network_filter
        if not accepts:
            return None
        if network_filter is None:
            return accepts[0]
        for a in accepts:
            if isinstance(a, dict) and a.get("network") == network_filter:
                return a
        return accepts[0]

