"""Interface contract — defined here, called by test."""
from dataclasses import dataclass


@dataclass
class SampleResult:
    index: int
    compile_ok: bool
    compile_attempts: int
    gen_pdf_path: str           # empty if compile failed
    vision_time: float
    codegen_time: float
    critic_score: float         # set by test runner
    critic_pass: bool
    diagnosis: str              # set by test runner
