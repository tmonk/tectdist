"""Typed input to the compatibility planner.

This deliberately uses only the standard library: it is also the contract
used by the benchmark runner and a future native implementation.
"""

from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class Invocation:
    invoked_name: str
    argv: Tuple[str, ...]
    cwd: str
    environment: Mapping[str, str]
