from dataclasses import dataclass
from typing import Optional

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

