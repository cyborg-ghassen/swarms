import os
from typing import Dict, Any, Optional
import importlib
import httpx

Account = None
try:
    eth_acc_mod = importlib.import_module("eth_account")
    Account = getattr(eth_acc_mod, "Account", None)
except Exception:
    Account = None


def _derive_address_from_private_key(priv: str) -> Optional[str]:
    if not priv:
        return None
    if Account is None:
        return None
    try:
        acct = Account.from_key(priv)
        return acct.address
    except Exception:
        return None


def x402_payment_tool(amount: float, currency: str = "USD", memo: Optional[str] = None, facilitator_url: Optional[str] = None, private_key: Optional[str] = None, network: Optional[str] = None) -> Dict[str, Any]:
    facilitator_url = facilitator_url or os.getenv("FACILITATOR_URL") or os.getenv("PAYAI_FACILITATOR_URL") or "https://facilitator.payai.network"
    private_key = private_key or os.getenv("X402_PRIVATE_KEY") or os.getenv("PAYAI_WALLET_PRIVATE_KEY")
    network = network or os.getenv("X402_NETWORK")
    headers = {"Content-Type": "application/json"}
    payload = {"amount": amount, "currency": currency}
    if memo:
        payload["metadata"] = {"memo": memo}
    if network:
        payload["network"] = network
    from_address = _derive_address_from_private_key(private_key)
    if from_address:
        payload["from_address"] = from_address

    with httpx.Client(timeout=30) as client:
        # Ensure facilitator reachable; if not, fallback to local mock
        try:
            l = client.get(f"{facilitator_url.rstrip('/')}/list", timeout=3)
            if l.status_code == 0 or l.status_code >= 500:
                facilitator_url = os.getenv("MOCK_FACILITATOR_URL", "http://127.0.0.1:8000")
        except Exception:
            facilitator_url = os.getenv("MOCK_FACILITATOR_URL", "http://127.0.0.1:8000")

        # Try create_payment first
        create_url = f"{facilitator_url.rstrip('/')}/create_payment"
        try:
            resp = client.post(create_url, json=payload, headers=headers)
            try:
                body = resp.json()
            except Exception:
                body = {"text": resp.text}
            result = {"status_code": resp.status_code, "body": body, "headers": dict(resp.headers)}
        except Exception as e:
            # network/DNS/connectivity error — return structured error instead of raising
            return {"status_code": 0, "error": str(e), "request_body": payload}

        # If create_payment is not implemented (404), fall back to verify
        if resp.status_code == 404:
            verify_url = f"{facilitator_url.rstrip('/')}/verify"
            try:
                resp2 = client.post(verify_url, json=payload, headers=headers)
                try:
                    body2 = resp2.json()
                except Exception:
                    body2 = {"text": resp2.text}
                return {"status_code": resp2.status_code, "body": body2, "headers": dict(resp2.headers)}
            except Exception as e:
                return {"status_code": 0, "error": str(e), "request_body": payload}

        return result


def x402_payment_full_flow(amount: float, currency: str = "USD", memo: Optional[str] = None, facilitator_url: Optional[str] = None, private_key: Optional[str] = None, network: Optional[str] = None) -> Dict[str, Any]:
    """
    High-level client-side flow that attempts create -> verify -> settle using the facilitator.
    Returns dict with keys: create, verify, settle (each may contain the response dict or error).
    """
    facilitator_url = facilitator_url or os.getenv("FACILITATOR_URL") or os.getenv("PAYAI_FACILITATOR_URL") or "https://facilitator.payai.network"
    headers = {"Content-Type": "application/json"}
    payload = {"amount": amount, "currency": currency}
    if memo:
        payload["metadata"] = {"memo": memo}
    if network:
        payload["network"] = network or os.getenv("X402_NETWORK")
    from_address = _derive_address_from_private_key(private_key or os.getenv("X402_PRIVATE_KEY"))
    if from_address:
        payload["from_address"] = from_address

    results = {}
    with httpx.Client(timeout=30) as client:
        # create
        try:
            r = client.post(f"{facilitator_url.rstrip('/')}/create_payment", json=payload, headers=headers)
            try:
                create_body = r.json()
            except Exception:
                create_body = {"text": r.text}
            results["create"] = {"status_code": r.status_code, "body": create_body, "headers": dict(r.headers)}
        except Exception as e:
            results["create"] = {"status_code": 0, "error": str(e), "request_body": payload}

        # verify (only if create succeeded; if create 404 then we try verify)
        try:
            create_status = results.get("create", {}).get("status_code", 0)
            if create_status == 404:
                # fallback: call verify
                r2 = client.post(f"{facilitator_url.rstrip('/')}/verify", json=payload, headers=headers)
                try:
                    verify_body = r2.json()
                except Exception:
                    verify_body = {"text": r2.text}
                results["verify"] = {"status_code": r2.status_code, "body": verify_body, "headers": dict(r2.headers)}
            elif 200 <= create_status < 300:
                r2 = client.post(f"{facilitator_url.rstrip('/')}/verify", json=payload, headers=headers)
                try:
                    verify_body = r2.json()
                except Exception:
                    verify_body = {"text": r2.text}
                results["verify"] = {"status_code": r2.status_code, "body": verify_body, "headers": dict(r2.headers)}
            else:
                results["verify"] = {"status_code": 0, "error": "create failed; skipping verify"}
        except Exception as e:
            results["verify"] = {"status_code": 0, "error": str(e)}

        # settle
        try:
            vstatus = results.get("verify", {}).get("status_code", 0)
            if 200 <= vstatus < 300:
                try:
                    r3 = client.post(f"{facilitator_url.rstrip('/')}/settle", json=payload, headers=headers)
                    try:
                        settle_body = r3.json()
                    except Exception:
                        settle_body = {"text": r3.text}
                    results["settle"] = {"status_code": r3.status_code, "body": settle_body, "headers": dict(r3.headers)}
                except Exception as e:
                    results["settle"] = {"status_code": 0, "error": str(e), "request_body": payload}
            else:
                 results["settle"] = {"status_code": 0, "error": "verify failed; skipping settle"}
        except Exception as e:
            results["settle"] = {"status_code": 0, "error": str(e)}

    return results
