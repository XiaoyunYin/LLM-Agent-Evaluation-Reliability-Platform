import os
import threading
import time
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.eval_case import EvalCase
from backend.app.eval_run import CandidateAnswer, JudgeScore, JudgeType, RunStatus
from backend.app.gpt4o_mini_judge import (
    JudgeOutputParseError,
    build_judge_prompt,
    parse_judge_output,
)


DEFAULT_SELF_HOSTED_JUDGE_ENDPOINT = "http://127.0.0.1:8001/v1/chat/completions"
DEFAULT_SELF_HOSTED_JUDGE_MODEL = "mistral-7b-instruct-v0.3-awq"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class SelfHostedJudgeConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    endpoint_url: str = DEFAULT_SELF_HOSTED_JUDGE_ENDPOINT
    model_name: str = DEFAULT_SELF_HOSTED_JUDGE_MODEL
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_seconds: float = Field(default=0.25, ge=0.0)
    api_key: str | None = None

    @field_validator("endpoint_url", "model_name")
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @classmethod
    def from_env(cls) -> "SelfHostedJudgeConfig":
        api_key = os.getenv("SELF_HOSTED_JUDGE_API_KEY")

        return cls(
            endpoint_url=os.getenv(
                "SELF_HOSTED_JUDGE_URL",
                DEFAULT_SELF_HOSTED_JUDGE_ENDPOINT,
            ),
            model_name=os.getenv(
                "SELF_HOSTED_JUDGE_MODEL",
                DEFAULT_SELF_HOSTED_JUDGE_MODEL,
            ),
            timeout_seconds=float(os.getenv("SELF_HOSTED_JUDGE_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("SELF_HOSTED_JUDGE_MAX_RETRIES", "2")),
            retry_backoff_seconds=float(
                os.getenv("SELF_HOSTED_JUDGE_RETRY_BACKOFF_SECONDS", "0.25")
            ),
            api_key=api_key if api_key and api_key.strip() else None,
        )


class SelfHostedJudgeEndpointError(Exception):
    pass


class SelfHostedJudge:
    judge_name = "self-hosted-7b-bulk-v0"
    judge_type = JudgeType.SELF_HOSTED_7B

    def __init__(
        self,
        config: SelfHostedJudgeConfig | None = None,
        max_parse_attempts: int = 2,
        session: Any | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.config = config or SelfHostedJudgeConfig.from_env()
        self.max_parse_attempts = max_parse_attempts
        self.session = session or requests.Session()
        self.sleep = sleep
        # Token accounting for throughput measured on the real workload rather
        # than a separate benchmark. Locked because bulk judging runs concurrently.
        self._usage_lock = threading.Lock()
        self.total_completion_tokens = 0
        self.total_prompt_tokens = 0
        self.usage_reported_calls = 0

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

        for _ in range(self.max_parse_attempts):
            try:
                raw_output = self._call_endpoint(prompt=prompt)
            except SelfHostedJudgeEndpointError as error:
                return self._failed_score(
                    candidate=candidate,
                    explanation=f"Self-hosted judge endpoint failed: {error}",
                )

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

        return self._failed_score(
            candidate=candidate,
            explanation=(
                "Self-hosted judge failed to return valid JSON after "
                f"{self.max_parse_attempts} parse attempt(s). Last error: {last_error}"
            ),
        )

    def _call_endpoint(self, prompt: str) -> str:
        payload = {
            "model": self.config.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json"}

        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        last_error: str | None = None

        for attempt_index in range(self.config.max_retries + 1):
            try:
                response = self.session.post(
                    self.config.endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )
            except requests.Timeout as error:
                last_error = f"request timed out after {self.config.timeout_seconds} second(s)"
                self._sleep_before_retry(attempt_index)
                continue
            except requests.RequestException as error:
                last_error = str(error)
                self._sleep_before_retry(attempt_index)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = f"HTTP {response.status_code}: {response.text}"
                self._sleep_before_retry(attempt_index)
                continue

            if response.status_code >= 400:
                raise SelfHostedJudgeEndpointError(
                    f"HTTP {response.status_code}: {response.text}"
                )

            try:
                data = response.json()
            except ValueError as error:
                raise SelfHostedJudgeEndpointError("endpoint returned non-JSON") from error

            self._record_usage(data.get("usage"))
            return self._extract_output_text(data)

        raise SelfHostedJudgeEndpointError(
            last_error or "endpoint did not return a response"
        )

    def _record_usage(self, usage: dict[str, Any] | None) -> None:
        """Accumulate token counts reported by the endpoint.

        Throughput has to be measured from the workload itself, not from a separate
        benchmark. Two disjoint measurements -- tok/s from a synthetic benchmark and
        an answer count from a different run at a different concurrency -- cannot be
        stated as one sentence without misrepresenting both. Counting tokens here
        makes "sustained X tok/s across N judged answers" a single measurement.

        Guarded by a lock because bulk judging runs this concurrently.
        """
        if not isinstance(usage, dict):
            return

        completion = usage.get("completion_tokens")
        prompt = usage.get("prompt_tokens")
        with self._usage_lock:
            if isinstance(completion, int):
                self.total_completion_tokens += completion
            if isinstance(prompt, int):
                self.total_prompt_tokens += prompt
            self.usage_reported_calls += 1

    def _extract_output_text(self, data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise SelfHostedJudgeEndpointError(
                "endpoint JSON did not match OpenAI-compatible chat completions format"
            ) from error

        if not isinstance(content, str) or not content.strip():
            raise SelfHostedJudgeEndpointError("endpoint returned blank message content")

        return content

    def _sleep_before_retry(self, attempt_index: int) -> None:
        if attempt_index >= self.config.max_retries:
            return

        self.sleep(self.config.retry_backoff_seconds * (2**attempt_index))

    def _failed_score(
        self,
        candidate: CandidateAnswer,
        explanation: str,
    ) -> JudgeScore:
        return JudgeScore(
            run_id=candidate.run_id,
            case_id=candidate.case_id,
            judge_name=self.judge_name,
            judge_type=self.judge_type,
            correctness=0.0,
            faithfulness=0.0,
            citation_quality=0.0,
            passed=False,
            explanation=explanation,
            trace_id=candidate.trace_id,
            status=RunStatus.FAILED,
        )

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
