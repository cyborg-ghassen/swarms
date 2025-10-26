from dataclasses import dataclass
from typing import Optional

@dataclass
class FacilitatorConfig:
    url: str
    timeout: Optional[int] = 10

