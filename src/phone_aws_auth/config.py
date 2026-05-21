"""Hardcoded names and runtime config for phone-aws-auth.

These names are part of the deployment contract: the Android app, deploy
scripts, and IAM policies all reference them directly. Do not parameterise.
"""

import os

STACK_NAME = "phone-aws-auth"
REGION = "eu-west-1"

GATE_TABLE_NAME = "phone-aws-gate"
VENDOR_LAMBDA_NAME = "phone-aws-vendor"
SANDBOX_ROLE_NAME = "phone-aws-sandbox-role"
LAMBDA_EXECUTION_ROLE_NAME = "phone-aws-lambda-role"
CONTROLLER_IAM_USER_NAME = "phone-aws-controller"

MODE_SANDBOX = "sandbox"
ALLOWED_MODES = (MODE_SANDBOX,)

# STS minimum. Hardcoded — the SDK auto-refreshes, so length doesn't matter to UX.
STS_SESSION_DURATION_SECONDS = 900

# Gate-open duration the phone may request.
DEFAULT_GATE_DURATION_SECONDS = 60 * 60
MAX_GATE_DURATION_SECONDS = 24 * 60 * 60


def role_arn_for_mode(mode: str) -> str:
    if mode != MODE_SANDBOX:
        raise ValueError(f"unsupported mode: {mode!r}")
    return os.environ["SANDBOX_ROLE_ARN"]
