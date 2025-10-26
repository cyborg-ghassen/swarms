import os
import json
from swarms.structs.x402_payment_agent import X402PaymentAgent
from swarms.tools.x402_payment_tool import x402_payment_tool


def demo_agent_payment():
    wallet_key = os.getenv("X402_PRIVATE_KEY") or os.getenv("PAYAI_WALLET_PRIVATE_KEY")
    agent = X402PaymentAgent(
        agent_name="x402-pay-agent",
        wallet_private_key=wallet_key,
        model_name="gpt-4o-mini",
        max_loops=1,
        streaming_on=False,
    )
    print("Creating payment session via agent...")
    res = agent.complete_payment_flow(amount=0.01, currency="USD", memo="test-payment")
    print(json.dumps(res, indent=2))


def demo_tool_payment():
    print("Calling payment tool directly...")
    res = x402_payment_tool(amount=0.01, currency="USD", memo="tool-payment")
    print(json.dumps(res, indent=2))


if __name__ == '__main__':
    print("FACILITATOR_URL:", os.getenv("FACILITATOR_URL"))
    print("X402_PRIVATE_KEY present:", bool(os.getenv("X402_PRIVATE_KEY")))
    demo_agent_payment()
    demo_tool_payment()
