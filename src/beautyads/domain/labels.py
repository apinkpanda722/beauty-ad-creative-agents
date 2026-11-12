"""Closed classification values from the draft v0 taxonomy."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HookType(StrEnum):
    question = "question"
    problem = "problem"
    result_first = "result_first"
    bold_claim = "bold_claim"
    product_first = "product_first"
    person_first = "person_first"
    other = "other"


class HookResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_type: HookType
