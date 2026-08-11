from enum import Enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator

class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JudgeType(str, Enum):
    RULE_BASED = "rule_based"
    GPT4O_MINI = "gpt4o_mini"
    SELF_HOSTED_7B = "self_hosted_7b"

class ReviewStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"

class EvalRun(BaseModel):
    run_id: str
    dataset_version: str
    provider_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: RunStatus = RunStatus.QUEUED

    @field_validator("run_id", "dataset_version", "provider_name")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

class CandidateAnswer(BaseModel):
    run_id: str
    case_id: str
    generated_answer: str
    tool_call: dict | None = None
    trace_id: str | None = None
    status: RunStatus = RunStatus.COMPLETED

    @field_validator("run_id", "case_id", "generated_answer")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

class JudgeScore(BaseModel):
    run_id: str
    case_id: str
    judge_name: str
    judge_type: JudgeType
    correctness: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    citation_quality: float = Field(ge=0.0, le=1.0)
    passed: bool
    explanation: str
    trace_id: str | None = None
    status: RunStatus = RunStatus.COMPLETED

    @field_validator("run_id", "case_id", "judge_name", "explanation")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

class ReviewCase(BaseModel):
    run_id: str
    case_id: str
    answer: str
    judge_a_score: float = Field(ge=0.0, le=1.0)
    judge_b_score: float = Field(ge=0.0, le=1.0)
    disagreement_reason: str
    human_label: str | None = None
    final_decision: str | None = None
    status: ReviewStatus = ReviewStatus.PENDING

    @field_validator("run_id", "case_id", "answer", "disagreement_reason")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value