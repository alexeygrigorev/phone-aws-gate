"""Shared helpers for the FastAPI shims that wrap Lambda handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request, Response


@dataclass
class FakeContext:
    aws_request_id: str


async def build_event(request: Request) -> dict:
    body_bytes = await request.body()
    return {
        "version": "2.0",
        "rawPath": request.url.path,
        "headers": {k.lower(): v for k, v in request.headers.items()},
        "body": body_bytes.decode("utf-8") if body_bytes else "",
        "requestContext": {
            "http": {
                "method": request.method,
                "path": request.url.path,
            }
        },
    }


def lambda_response_to_http(result: dict) -> Response:
    status = int(result.get("statusCode", 200))
    headers = result.get("headers") or {}
    body = result.get("body", "")
    return Response(content=body, status_code=status, headers=headers)


def fresh_context() -> FakeContext:
    return FakeContext(aws_request_id=uuid.uuid4().hex)
