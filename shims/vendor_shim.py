"""FastAPI shim around the vendor Lambda handler.

Run locally with:
    uv run uvicorn shims.vendor_shim:app --port 8002 --reload

The Lambda handler is pure — we only translate HTTP <-> Lambda event/response here.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from phone_aws_auth.handlers.vendor import handler as vendor_handler

from . import _common

app = FastAPI(title="phone-aws-auth vendor (local shim)")


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy(request: Request, full_path: str):
    event = await _common.build_event(request)
    result = vendor_handler(event, _common.fresh_context())
    return _common.lambda_response_to_http(result)
