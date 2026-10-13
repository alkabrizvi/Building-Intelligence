import json
import time
import uuid
from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from building_with_rag.contracts import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCard,
    ModelList,
    OpenAIError,
    OpenAIErrorEnvelope,
    QueryRequest,
    QueryResult,
    SemanticFilters,
)
from building_with_rag.patterns import run_pattern
from building_with_rag.registry import MODE_BY_MODEL_ID, MODEL_IDS
from building_with_rag.settings import get_settings

app = FastAPI(title="Building with RAG")


def _openai_error(status: int, message: str, code: str | None = None, param: str | None = None):
    body = OpenAIErrorEnvelope(error=OpenAIError(message=message, code=code, param=param))
    return JSONResponse(status_code=status, content=body.model_dump())


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/v1/chat/"):
        return _openai_error(exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/v1/chat/"):
        # Report the field location only; never echo submitted input.
        errors = exc.errors()
        where = ".".join(str(p) for p in errors[0]["loc"][1:]) if errors else ""
        return _openai_error(400, "Invalid request.", code="invalid_request", param=where or None)
    return JSONResponse(
        status_code=422,
        content={"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/query", response_model=QueryResult)
def query(request: QueryRequest) -> QueryResult:
    # The seed resolves only its fixed local demo caller.
    request.caller_id = get_settings().webui_demo_caller_id
    return run_pattern(request)


@app.get("/v1/models", response_model=ModelList)
def models() -> ModelList:
    return ModelList(data=[ModelCard(id=m) for m in MODEL_IDS.values()])


def _text(content: str | list[dict]) -> str:
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content if p.get("type") == "text")


def _answer_text(result: QueryResult) -> str:
    if result.generation and result.generation.answer:
        return result.generation.answer
    return result.message


def _stream(completion_id: str, created: int, model: str, text: str) -> Iterator[str]:
    def chunk(delta: dict, finish: str | None = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    yield chunk({"role": "assistant"})
    yield chunk({"content": text})
    yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest):
    opts = request.rag_options
    pattern = (opts.pattern if opts and opts.pattern else None) or MODE_BY_MODEL_ID.get(
        request.model
    )
    if pattern is None:
        return _openai_error(404, "Unknown model.", code="model_not_found", param="model")
    question = next((_text(m.content) for m in reversed(request.messages) if m.role == "user"), "")
    question = question.strip()
    if not question:
        return _openai_error(400, "A user message is required.", param="messages")
    if len(question) > 4000:
        return _openai_error(400, "The user message is too long.", param="messages")

    filters = None
    if opts and (opts.act or opts.status or opts.access_level):
        filters = SemanticFilters(act=opts.act, status=opts.status, access_level=opts.access_level)
    query_request = QueryRequest(
        question=question,
        pattern=pattern,
        caller_id=get_settings().webui_demo_caller_id,
        filters=filters,
        limit=(opts.limit if opts and opts.limit else 5),
        generate_answer=True,
        required_acts=opts.required_acts if opts else None,
        chapter=opts.chapter if opts else None,
    )
    text = _answer_text(run_pattern(query_request))

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    if request.stream:
        return StreamingResponse(
            _stream(completion_id, created, request.model, text), media_type="text/event-stream"
        )
    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=request.model,
        choices=[ChatCompletionChoice(message=ChatCompletionMessage(content=text))],
    )
