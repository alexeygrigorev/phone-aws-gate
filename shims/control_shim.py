"""FastAPI shim around the control Lambda handler.

Run locally with:
    uv run uvicorn shims.control_shim:app --port 8001 --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from phone_aws_auth.handlers.control import handler as control_handler

from . import _common

app = FastAPI(title="phone-aws-auth control (local shim)")


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, full_path: str):
    event = await _common.build_event(request)
    result = control_handler(event, _common.fresh_context())
    return _common.lambda_response_to_http(result)
