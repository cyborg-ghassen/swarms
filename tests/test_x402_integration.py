import importlib.util
import sys
from httpx import Response
from httpx import Request
import pytest

spec = importlib.util.spec_from_file_location("x402_tool", r"D:\Projects\swarms\swarms\tools\x402_payment_tool.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
x402_payment_tool = module.x402_payment_tool


class DummyTransport:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self.json_body = json_body or {"id": "tx_12345", "status": "success"}
        self.headers = headers or {"X-PAYMENT-RESPONSE": "tx_12345"}

    def request(self, method, url, headers=None, json=None):
        return Response(status_code=self.status_code, json=self.json_body, headers=self.headers, request=Request(method=method, url=url))


def test_x402_payment_tool_success(monkeypatch):
    def fake_post(url, json=None, headers=None):
        return Response(status_code=200, json={"id": "tx_12345", "status": "success"}, headers={"X-PAYMENT-RESPONSE": "tx_12345"}, request=Request(method="POST", url=url))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, json=None, headers=None):
            return fake_post(url, json=json, headers=headers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("httpx.Client", FakeClient)

    res = x402_payment_tool(amount=0.01, currency="USD", memo="unit-test-payment", facilitator_url="https://facilitator.payai.network")

    assert res["status_code"] == 200
    assert res["body"]["status"] == "success"
    assert any(k.lower() == "x-payment-response" for k in res["headers"].keys())


if __name__ == '__main__':
    pytest.main(["-q", __file__])
