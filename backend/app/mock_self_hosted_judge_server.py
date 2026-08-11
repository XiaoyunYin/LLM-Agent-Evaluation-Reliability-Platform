import json
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 0
    mock_mode: str = "valid"


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str = "mock-self-hosted-judge-response"
    object: str = "chat.completion"
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )


def create_mock_self_hosted_judge_app() -> FastAPI:
    app = FastAPI(title="Mock Self-Hosted 7B Judge")

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "mock-self-hosted-judge"}

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
        if not request.messages:
            raise HTTPException(status_code=400, detail="At least one message is required")

        if request.mock_mode == "malformed":
            content = "This mock response is intentionally not JSON."
        else:
            content = json.dumps(_build_mock_judge_output(request))

        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessage(role="assistant", content=content)
                )
            ],
        )

    return app


def _build_mock_judge_output(request: ChatCompletionRequest) -> dict[str, Any]:
    prompt = request.messages[-1].content.lower()

    if "candidate answer:\n4" in prompt and "expected answer:\n4" in prompt:
        correctness = 1.0
        faithfulness = 1.0
        passed = True
        explanation = "Mock 7B judge found the candidate answer matches the expected answer."
    else:
        correctness = 0.5
        faithfulness = 0.5
        passed = False
        explanation = "Mock 7B judge returned a deterministic placeholder grade."

    return {
        "correctness": correctness,
        "faithfulness": faithfulness,
        "citation_quality": 0.0,
        "passed": passed,
        "explanation": explanation,
    }


app = create_mock_self_hosted_judge_app()
