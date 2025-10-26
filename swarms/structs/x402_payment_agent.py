import os
import logging
from typing import Optional, Dict, Any

import httpx

import importlib

Account = None
try:
    eth_acc_mod = importlib.import_module("eth_account")
    Account = getattr(eth_acc_mod, "Account", None)
except Exception:
    Account = None


from swarms.structs.agent import Agent

logger = logging.getLogger(__name__)


class X402PaymentAgent(Agent):
    def __init__(
        self,
        facilitator_url: str = "https://facilitator.payai.network",
        wallet_private_key: Optional[str] = None,
        network: Optional[str] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.facilitator_url = os.getenv("FACILITATOR_URL", facilitator_url).rstrip("/")
        self.wallet_private_key = wallet_private_key or os.getenv("X402_PRIVATE_KEY") or os.getenv("PAYAI_WALLET_PRIVATE_KEY")
        self.network = network or os.getenv("X402_NETWORK")
        self.wallet_address = None
        self.account = None
        self._http_client = httpx.Client(timeout=30)
        if self.wallet_private_key:
            try:
                self.init_wallet()
            except Exception as e:
                logger.warning(f"failed initializing wallet: {e}")

        # cache for facilitator discovery
        self._facilitator_info: Dict[str, Any] = {}

        # ensure the facilitator is reachable; if not, fall back to local mock
        try:
            info = self.discover_facilitator(timeout=3)
            if info.get("status_code", 0) == 0 or info.get("status_code") >= 500:
                # fallback
                logger.warning(f"facilitator {self.facilitator_url} unreachable or returned {info.get('status_code')}; falling back to local mock")
                self.facilitator_url = os.getenv("MOCK_FACILITATOR_URL", "http://127.0.0.1:8000")
                # refresh info
                try:
                    self.discover_facilitator()
                except Exception:
                    pass
        except Exception:
            # on exception, also fallback to mock
            logger.warning("error discovering facilitator; falling back to local mock")
            self.facilitator_url = os.getenv("MOCK_FACILITATOR_URL", "http://127.0.0.1:8000")
            try:
                self.discover_facilitator()
            except Exception:
                pass

    def init_wallet(self):
        if Account is None:
            raise RuntimeError("eth_account not installed; cannot initialize wallet from private key")
        priv = self.wallet_private_key
        if priv and not priv.startswith("0x"):
            priv = "0x" + priv
        acct = Account.from_key(priv)
        self.account = acct
        self.wallet_address = acct.address
        return self.wallet_address

    def discover_facilitator(self, timeout: int = 5) -> Dict[str, Any]:
        """Call /list on the facilitator and cache the response for diagnostics and network support checks."""
        try:
            url = f"{self.facilitator_url.rstrip('/')}/list"
            r = self._http_client.get(url, timeout=timeout)
            try:
                payload = r.json()
            except Exception:
                payload = {"text": r.text}
            info = {"status_code": r.status_code, "payload": payload, "headers": dict(r.headers)}
        except Exception as e:
            info = {"status_code": 0, "error": str(e)}
        self._facilitator_info = info
        return info

    def paid_api_call(
        self,
        path: str,
        amount: float,
        currency: str = "USD",
        metadata: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        url = f"{self.facilitator_url}/{path.lstrip('/') }"
        headers = {"Content-Type": "application/json"}
        # Try to be flexible about amount shape: send as number and as string in diagnostics
        body = {"amount": amount, "currency": currency}
        if metadata:
            body["metadata"] = metadata
        if self.wallet_address:
            body["from_address"] = self.wallet_address
        if self.network:
            body["network"] = self.network
        try:
            resp = self._http_client.post(url, headers=headers, json=body, timeout=timeout)
            try:
                payload = resp.json()
            except Exception:
                payload = {"text": resp.text}
            result = {
                "status_code": resp.status_code,
                "payload": payload,
                "headers": dict(resp.headers),
            }
            # attach diagnostics when non-2xx
            if not (200 <= resp.status_code < 300):
                result["request_body"] = body
                result["response_text"] = resp.text
                # attempt to discover facilitator info if not known
                if not self._facilitator_info:
                    try:
                        self.discover_facilitator()
                        result["facilitator_info"] = self._facilitator_info
                    except Exception:
                        pass
            return result
        except Exception as e:
            logger.error(f"paid_api_call error: {e}")
            return {"status_code": 0, "error": str(e)}

    def create_payment_session(self, amount: float, currency: str = "USD", memo: Optional[str] = None):
        metadata = {"memo": memo} if memo else None
        create_res = self.paid_api_call("create_payment", amount=amount, currency=currency, metadata=metadata)
        # If the facilitator returns 404, try verify. If it returns 400, include diagnostics and try verify anyway.
        status = create_res.get("status_code", 0)
        if status == 404:
            logger.info("facilitator returned 404 for /create_payment; falling back to /verify for intent creation")
            verify_res = self.paid_api_call("verify", amount=amount, currency=currency, metadata=metadata)
            if 200 <= verify_res.get("status_code", 0) < 300:
                return {
                    "status_code": verify_res.get("status_code"),
                    "payload": {
                        "id": verify_res.get("payload", {}).get("id", None) or verify_res.get("payload"),
                        "status": "verified-as-create",
                        "received": verify_res.get("payload", {}).get("received", verify_res.get("payload")),
                    },
                    "headers": verify_res.get("headers"),
                }
            return verify_res
        elif status == 400:
            # Bad request from facilitator: include request/response diagnostics and attempt verify as fallback
            logger.warning(f"create_payment returned 400: {create_res.get('payload')}. Attempting /verify fallback and including diagnostics.")
            # try verify anyway
            verify_res = self.paid_api_call("verify", amount=amount, currency=currency, metadata=metadata)
            # Attach diagnostics to create_res for caller visibility
            create_res.setdefault("diagnostics", {})
            create_res["diagnostics"]["note"] = "create_payment returned 400; see response_text and request_body"
            create_res["diagnostics"]["facilitator_list"] = self.discover_facilitator()
            # Return combined result where create contains diagnostics and verify result included by caller's complete_flow
            # Caller will proceed to verify/settle based on verify_res status
            return create_res
        return create_res

    def complete_payment_flow(self, amount: float, currency: str = "USD", memo: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
        """
        High-level flow: create payment intent, verify the intent, then settle the payment.

        Returns a dictionary with keys: create, verify, settle each containing the facilitator response.
        This is intentionally simple: it delegates to the facilitator endpoints and returns their JSON.
        """
        result: Dict[str, Any] = {}
        try:
            create_res = self.create_payment_session(amount=amount, currency=currency, memo=memo)
            result["create"] = create_res
        except Exception as e:
            result["create"] = {"status_code": 0, "error": str(e)}

        verify_payload = None
        try:
            status = result.get("create", {}).get("status_code", 0)
            # Normal path: if create succeeded, call verify
            if 200 <= status < 300:
                verify_res = self.paid_api_call("verify", amount=amount, currency=currency, metadata={"memo": memo} if memo else None, timeout=timeout)
            # Fallback: some facilitators (e.g. PayAI) may return 400 for create and expect verify/settle directly
            elif status in (400, 404):
                logger.info(f"create returned status {status}; attempting verify fallback")
                # First try the simple verify payload
                verify_res = self.paid_api_call("verify", amount=amount, currency=currency, metadata={"memo": memo} if memo else None, timeout=timeout)
                # If verify did not succeed, attempt an EIP-712 signed verify fallback
                vstatus = verify_res.get("status_code", 0)
                if not (200 <= vstatus < 300):
                    logger.info(f"simple verify returned {vstatus}; attempting verify_with_signature fallback")
                    sig_res = self.verify_with_signature(amount=amount, currency=currency, memo=memo)
                    # If signature-based verify succeeded, use that result
                    if 200 <= sig_res.get("status_code", 0) < 300:
                        verify_res = sig_res
                    else:
                        # attach both diagnostics to the response for caller visibility
                        try:
                            verify_res.setdefault("diagnostics", {})
                            verify_res["diagnostics"]["create_response"] = result.get("create")
                            verify_res["diagnostics"]["signature_attempt"] = sig_res
                        except Exception:
                            pass
                else:
                    # attach create diagnostics to the verify result for caller visibility
                    try:
                        verify_res.setdefault("diagnostics", {})
                        verify_res["diagnostics"]["create_response"] = result.get("create")
                    except Exception:
                        pass
            else:
                verify_res = {"status_code": 0, "error": "create failed; skipping verify"}
            result["verify"] = verify_res
        except Exception as e:
            result["verify"] = {"status_code": 0, "error": str(e)}

        try:
            vstatus = result.get("verify", {}).get("status_code", 0)
            if 200 <= vstatus < 300:
                settle_res = self.paid_api_call("settle", amount=amount, currency=currency, metadata={"memo": memo} if memo else None, timeout=timeout)
            else:
                # If verify returned 400 or 404, attempt settle as a last resort
                if vstatus in (400, 404):
                    logger.info(f"verify returned status {vstatus}; attempting settle fallback")
                    settle_res = self.paid_api_call("settle", amount=amount, currency=currency, metadata={"memo": memo} if memo else None, timeout=timeout)
                    try:
                        settle_res.setdefault("diagnostics", {})
                        settle_res["diagnostics"]["verify_response"] = result.get("verify")
                    except Exception:
                        pass
                else:
                    settle_res = {"status_code": 0, "error": "verify failed; skipping settle"}
            result["settle"] = settle_res
        except Exception as e:
            result["settle"] = {"status_code": 0, "error": str(e)}

        return result

    def _build_eip712_intent(self, amount: float, currency: str = "USD", memo: Optional[str] = None) -> Dict[str, Any]:
        """Build a generic EIP-712 structured data object for a payment intent.

        This is intentionally generic: real facilitators may expect a different schema. The intent
        includes a minimal domain and message with amount, currency, from_address, to_address (if available), memo and network.
        """
        domain = {
            "name": "x402 Payment",
            "version": "1",
            "chainId": 1,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        }
        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Payment": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "string"},
                {"name": "currency", "type": "string"},
                {"name": "memo", "type": "string"},
                {"name": "network", "type": "string"},
            ],
        }
        message = {
            "from": self.wallet_address or "0x0000000000000000000000000000000000000000",
            "to": os.getenv("PAYAI_MERCHANT_ADDRESS") or os.getenv("ADDRESS") or "0x0000000000000000000000000000000000000000",
            "amount": str(amount),
            "currency": currency,
            "memo": memo or "",
            "network": self.network or "",
        }
        return {"types": types, "domain": domain, "primaryType": "Payment", "message": message}

    def _sign_eip712(self, structured_data: Dict[str, Any]) -> Optional[str]:
        """Sign EIP-712 structured data using eth_account if available. Returns hex signature or None."""
        if Account is None:
            logger.debug("eth_account not installed; cannot sign EIP-712 payload")
            return None
        try:
            from eth_account.messages import encode_structured_data

            encoded = encode_structured_data(structured_data)
            # ensure private key has 0x
            priv = self.wallet_private_key
            if priv and not priv.startswith("0x"):
                priv = "0x" + priv
            signed = Account.sign_message(encoded, priv)
            return signed.signature.hex()
        except Exception as e:
            logger.warning(f"failed signing structured data: {e}")
            return None

    def verify_with_signature(self, amount: float, currency: str = "USD", memo: Optional[str] = None) -> Dict[str, Any]:
        """Build an EIP-712 intent, sign it, and POST to /verify as a fallback for facilitators expecting signed intents.

        The body shape is generic: { "eip712": <structured_data>, "signature": <hex>, "from_address": <addr>, "network": <network> }
        Real facilitators may require different fields; this is a best-effort fallback.
        """
        structured = self._build_eip712_intent(amount=amount, currency=currency, memo=memo)
        signature = self._sign_eip712(structured)
        body = {"eip712": structured, "signature": signature, "from_address": self.wallet_address, "network": self.network}
        url = f"{self.facilitator_url.rstrip('/')}/verify"
        headers = {"Content-Type": "application/json"}
        try:
            resp = self._http_client.post(url, json=body, headers=headers, timeout=30)
            try:
                payload = resp.json()
            except Exception:
                payload = {"text": resp.text}
            return {"status_code": resp.status_code, "payload": payload, "headers": dict(resp.headers), "request_body": body}
        except Exception as e:
            return {"status_code": 0, "error": str(e), "request_body": body}
