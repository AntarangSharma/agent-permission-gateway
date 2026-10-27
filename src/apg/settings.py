"""Explicit local runtime limits; price estimates are supplied by the operator."""

import os
from pathlib import Path

from pydantic import Field

from apg.models import StrictModel


class Limits(StrictModel):
    calls: int = Field(default=12, ge=1, le=100)
    output_tokens: int = Field(default=700, ge=128, le=8000)
    retries: int = Field(default=1, ge=0, le=3)
    seconds: float = Field(default=90.0, gt=0)
    spend_usd: float = Field(default=0.15, gt=0)
    input_per_million: float = Field(default=5.0, ge=0)
    output_per_million: float = Field(default=20.0, ge=0)

    @classmethod
    def environment(cls) -> "Limits":
        return cls.model_validate(
            {
                "calls": int(os.getenv("APG_MAX_CALLS", "12")),
                "output_tokens": int(os.getenv("APG_MAX_OUTPUT_TOKENS", "700")),
                "retries": int(os.getenv("APG_MAX_RETRIES", "1")),
                "seconds": float(os.getenv("APG_MAX_SECONDS", "90")),
                "spend_usd": float(os.getenv("APG_MAX_SPEND_USD", "0.15")),
                "input_per_million": float(os.getenv("APG_INPUT_PRICE", "5")),
                "output_per_million": float(os.getenv("APG_OUTPUT_PRICE", "20")),
            }
        )


def data_root() -> Path:
    return Path(os.getenv("APG_DATA_DIR", ".runtime"))
