"""Structured output with validation and one repair attempt.

Every provider's JSON goes through the same Pydantic model at this boundary. If it is
malformed or fails validation, the model gets exactly one more chance, told what was
wrong; that rescues most slips by smaller or local models for the cost of one call.
Truncated answers are not retried: the same request would be cut off again.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from postloom.adapters.llm.base import Effort, InvalidOutputError
from postloom.adapters.llm.gateway import LlmGateway
from postloom.adapters.llm.http import JsonObject
from postloom.application.errors import ExtractionError, ProviderUnavailableError
from postloom.application.ports.usage import Task

T = TypeVar("T", bound=BaseModel)


def structured(
    gateway: LlmGateway,
    task: Task,
    model: str,
    result: type[T],
    *,
    system: str,
    prompt: str,
    schema: JsonObject,
    schema_name: str,
    temperature: float,
    max_output_tokens: int,
    failure: str,
    effort: Effort = "low",
    fallbacks: Sequence[str] = (),
) -> T:
    """Ask for ``schema`` and return it validated as ``result``; raise ``failure`` if not.

    When ``model`` is overloaded or unreachable even after the gateway's retries, the
    ``fallbacks`` are tried in order before giving up.
    """
    models = list(dict.fromkeys([model, *fallbacks]))
    busy: list[str] = []
    last: ProviderUnavailableError | None = None
    for current in models:
        try:
            return _ask(
                gateway,
                task,
                current,
                result,
                system=system,
                prompt=prompt,
                schema=schema,
                schema_name=schema_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                failure=failure,
                effort=effort,
            )
        except ProviderUnavailableError as error:
            busy.append(current)
            last = error
    if len(busy) == 1 and last is not None:
        raise last
    raise ProviderUnavailableError(
        f"Every model postloom can use for this is overloaded right now ({', '.join(busy)}). "
        "Try again in a few minutes."
    ) from last


def _ask(
    gateway: LlmGateway,
    task: Task,
    model: str,
    result: type[T],
    *,
    system: str,
    prompt: str,
    schema: JsonObject,
    schema_name: str,
    temperature: float,
    max_output_tokens: int,
    failure: str,
    effort: Effort,
) -> T:
    request = prompt
    problem = ""
    for attempt in range(2):
        try:
            raw = gateway.json(
                task,
                model,
                system=system,
                prompt=request,
                schema=schema,
                schema_name=schema_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                effort=effort,
            )
            return result.model_validate(raw)
        except InvalidOutputError as error:
            problem = str(error)
        except ValidationError as error:
            problem = describe(error)
        if attempt == 0:
            request = (
                f"{prompt}\n\nYour previous answer could not be used: {problem} "
                "Answer again with one JSON object that matches the schema exactly."
            )
    raise ExtractionError(f"{failure} ({problem})")


def describe(error: ValidationError) -> str:
    issues = [
        f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}" for e in error.errors()[:5]
    ]
    return "invalid fields: " + "; ".join(issues) + "."
