import json
import os
from typing import Any



from backend.app.eval_run import JudgeScore, JudgeType, RunStatus
from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer
from pydantic import BaseModel, Field, ValidationError, field_validator


GPT4O_MINI_JUDGE_MODEL = "gpt-4o-mini"




class GPT4oMiniJudgeOutput(BaseModel):
    correctness: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    citation_quality: float = Field(ge=0.0, le=1.0)
    passed: bool
    explanation: str

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

class JudgeOutputParseError(Exception):
    pass


def parse_judge_output(raw_output: str) -> GPT4oMiniJudgeOutput:
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as error:
        raise JudgeOutputParseError("Judge returned invalid JSON.") from error

    try:
        return GPT4oMiniJudgeOutput(**data)
    except ValidationError as error:
        raise JudgeOutputParseError("Judge JSON did not match the expected schema.") from error

def build_judge_prompt(
    case: EvalCase,
    candidate: CandidateAnswer,
    retrieved_context: list[str] | None = None,
) -> str:
    context_block = "\n\n".join(retrieved_context or [])

    if not context_block:
        context_block = "No retrieved context was provided."

    return f"""
You are an LLM judge grading one candidate answer.

Grade the answer on three separate dimensions:

1. correctness:
- 1.0 means the candidate answer fully answers the question and matches the expected answer.
- 0.5 means the answer is partially correct but incomplete or imprecise.
- 0.0 means the answer is wrong or does not answer the question.

2. faithfulness:
- 1.0 means every factual claim is supported by the retrieved context or the expected answer.
- 0.5 means some claims are supported, but some are unsupported or unclear.
- 0.0 means the answer contains major unsupported claims or contradicts the context.

3. citation_quality:
- 1.0 means the answer uses relevant chunk citations correctly, such as [chunk_123].
- 0.5 means citations are present but incomplete, vague, or only partly relevant.
- 0.0 means citations are missing, invalid, or misleading.
- If no retrieved context was provided, use 0.0 for citation_quality.

Return JSON only. Do not include markdown, prose, or code fences.

The JSON must have exactly these fields:
{{
  "correctness": 0.0,
  "faithfulness": 0.0,
  "citation_quality": 0.0,
  "passed": false,
  "explanation": "short explanation"
}}

Use scores between 0.0 and 1.0.
Set passed to true only when correctness >= 0.8 and faithfulness >= 0.8.

Question:
{case.question}

Expected answer:
{case.expected_answer}

Candidate answer:
{candidate.generated_answer}

Retrieved context:
{context_block}
""".strip()


class GPT4oMiniJudge:
    judge_name = "gpt-4o-mini-validation-v0"
    judge_type = JudgeType.GPT4O_MINI

    def __init__(
        self,
        model_name: str = GPT4O_MINI_JUDGE_MODEL,
        api_key_env: str = "OPENAI_API_KEY",
        max_parse_attempts: int = 2,
        client: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.api_key_env = api_key_env
        self.max_parse_attempts = max_parse_attempts

        if client is not None:
            self.client = client
            return

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(
                f"Missing {api_key_env}. Set it before using GPT4oMiniJudge."
            )

        try:
            from openai import OpenAI
        except ImportError as error:
            raise ValueError(
                "The openai package is required for real GPT-4o-mini judging. "
                "Install dependencies before using GPT4oMiniJudge without a fake client."
            ) from error

        self.client = OpenAI(api_key=api_key)

    def judge_candidate_answer(
        self,
        case: EvalCase,
        candidate: CandidateAnswer,
        retrieved_context: list[str] | None = None,
    ) -> JudgeScore:
        prompt = build_judge_prompt(
            case=case,
            candidate=candidate,
            retrieved_context=retrieved_context,
        )

        parse_errors: list[str] = []

        for attempt_number in range(1, self.max_parse_attempts + 1):
            raw_output = self._call_model(prompt=prompt)

            try:
                parsed = parse_judge_output(raw_output)
            except JudgeOutputParseError as error:
                parse_errors.append(str(error))
                prompt = self._build_retry_prompt(
                    original_prompt=prompt,
                    malformed_output=raw_output,
                    parse_error=str(error),
                )
                continue

            return JudgeScore(
                run_id=candidate.run_id,
                case_id=candidate.case_id,
                judge_name=self.judge_name,
                judge_type=self.judge_type,
                correctness=parsed.correctness,
                faithfulness=parsed.faithfulness,
                citation_quality=parsed.citation_quality,
                passed=parsed.passed,
                explanation=parsed.explanation,
                trace_id=candidate.trace_id,
            )

        last_error = parse_errors[-1] if parse_errors else "Unknown parse error."

        return JudgeScore(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            judge_name=self.judge_name,
            judge_type=self.judge_type,
            correctness=0.0,
            faithfulness=0.0,
            citation_quality=0.0,
            passed=False,
            explanation=(
                "GPT-4o-mini judge failed to return valid JSON after "
                f"{self.max_parse_attempts} attempt(s). Last error: {last_error}"
            ),
            trace_id=candidate.trace_id,
            status=RunStatus.FAILED,
        )

    def _call_model(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model_name,
            input=prompt,
            temperature=0,
        )
        return response.output_text

    def _build_retry_prompt(
        self,
        original_prompt: str,
        malformed_output: str,
        parse_error: str,
    ) -> str:
        return f"""
{original_prompt}

Your previous response could not be parsed.

Parse error:
{parse_error}

Previous malformed response:
{malformed_output}

Return the corrected JSON object only.
""".strip()