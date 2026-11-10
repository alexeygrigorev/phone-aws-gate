"""Configuration for phone-aws-auth.

Kept tiny and dependency-free so both the Lambda handler and the CLI tools
can import it.
"""

from __future__ import annotations

import os


GATE_TABLE_NAME = os.environ.get("GATE_TABLE_NAME", "phone-aws-gate")
REGION = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "eu-west-1"))

# Only sandbox is wired up here. When a `main` mode is eventually added,
# it should live in its own handler or behind a separate IAM boundary —
# not just a second dict entry.
MODE_SANDBOX = "sandbox"
ALLOWED_MODES = (MODE_SANDBOX,)

ALLOWED_RESOURCES = ("aws-sandbox", "aws-main", "browser", "sms")
DEFAULT_SCOPES = {
    "aws-sandbox": "sandbox",
    "aws-main": "main",
    "browser": "desktop",
    "sms": "login",
}

# STS minimum. Hardcoded — the SDK auto-refreshes, so length doesn't matter to UX.
STS_SESSION_DURATION_SECONDS = 900

# Gate-open duration the phone may request.
DEFAULT_GATE_DURATION_SECONDS = 60 * 60
MAX_GATE_DURATION_SECONDS = 24 * 60 * 60
REQUEST_PROMPT_TTL_SECONDS = 15 * 60


def role_arn_for_mode(mode: str) -> str:
    if mode != MODE_SANDBOX:
        raise ValueError(f"unsupported mode: {mode!r}")
    return os.environ["SANDBOX_ROLE_ARN"]


MAIN_ROLE_ARN = "arn:aws:iam::387546586013:role/aws-gate-main-access"
