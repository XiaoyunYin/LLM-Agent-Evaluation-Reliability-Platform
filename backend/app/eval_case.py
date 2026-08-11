from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator

class TaskType(str, Enum):
    DIRECT_QA = "direct_qa"
    RAG_QA = "rag_qa"
    PROMPT_COMPARISON = "prompt_comparison"
    JUDGE_BEHAVIOR = "judge_behavior"
    REGRESSION_STABILITY = "regression_stability"
    AGENTIC_TOOL_CALLING = "agentic_tool_calling"

class EvalCase(BaseModel):
    id: str
    question: str
    expected_answer: str
    task_type: TaskType
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "question", "expected_answer")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value