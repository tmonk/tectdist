"""Typed, side-effect-free compilation planning data."""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ResolvedEngine:
    path: str
    realpath: str
    mtime_ns: Optional[int]


@dataclass(frozen=True)
class CompilationPlan:
    program: str
    engine: ResolvedEngine
    engine_args: Tuple[str, ...]
    input_path: Optional[str]
    output_directory: str
    rename: Optional[Tuple[str, str, str]]
    requires_index_detection: bool
    help_requested: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    generated_files: Tuple[str, ...] = ()
    engine_passes: int = 0
