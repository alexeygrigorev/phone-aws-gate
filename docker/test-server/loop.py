"""Simulates the remote server.

Validates the AWS SDK credential-resolution chain by using boto3's native
support for AWS_CONTAINER_CREDENTIALS_FULL_URI + AWS_CONTAINER_AUTHORIZATION_TOKEN.

Each tick:
  1. Build a fresh boto3.Session()
  2. Force credential resolution (get_frozen_credentials)
  3. Print resolved AccessKeyId + expiration
  4. (Optional, if TRY_STS=1) call sts:GetCallerIdentity with a short timeout
     to demonstrate the SDK signs requests with the resolved creds.

What "success" looks like:
  - Gate closed: NoCredentials / CredentialRetrievalError (provider failed)
  - Gate open:   creds=ASIA-FAKE-SANDBOX exp=...   (SDK fetched and parsed)
  - With TRY_STS=1 and real internet: STS rejects with InvalidClientTokenId
"""

from __future__ import annotations

import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    CredentialRetrievalError,
    EndpointConnectionError,
    NoCredentialsError,
)

INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "5"))
TRY_STS = os.environ.get("TRY_STS") == "1"
STS_TIMEOUT = float(os.environ.get("STS_TIMEOUT", "3"))
STS_ENDPOINT_URL = os.environ.get("STS_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL_STS")


def resolve_creds() -> tuple[str, str | None, str | None]:
    """Returns (status, access_key, message)."""
    sess = boto3.Session()
    try:
        creds = sess.get_credentials()
    except CredentialRetrievalError as e:
        return ("gate-closed", None, str(e))
    except Exception as e:
        return ("error", None, f"{type(e).__name__}: {e}")

    if creds is None:
        return ("no-creds", None, "boto3 returned no credentials")

    try:
        frozen = creds.get_frozen_credentials()
    except CredentialRetrievalError as e:
        return ("gate-closed", None, str(e))
    except Exception as e:
        return ("error", None, f"{type(e).__name__}: {e}")

    return ("ok", frozen.access_key, None)


def try_sts(access_key: str) -> str:
    config = Config(connect_timeout=STS_TIMEOUT, read_timeout=STS_TIMEOUT, retries={"max_attempts": 1})
    kwargs = {"config": config}
    if STS_ENDPOINT_URL:
        kwargs["endpoint_url"] = STS_ENDPOINT_URL
    sts = boto3.client("sts", **kwargs)
    try:
        arn = sts.get_caller_identity()["Arn"]
        return f"STS ok: {arn}"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        return f"STS rejected ({code}) — SDK loop OK"
    except (EndpointConnectionError, NoCredentialsError) as e:
        return f"STS unreachable: {type(e).__name__}"
    except Exception as e:
        return f"STS error: {type(e).__name__}: {e}"


def main() -> None:
    print(f"test-server: AWS_CONTAINER_CREDENTIALS_FULL_URI={os.environ.get('AWS_CONTAINER_CREDENTIALS_FULL_URI')!r}")
    print(f"test-server: STS_ENDPOINT_URL={STS_ENDPOINT_URL!r}")
    print(f"test-server: polling every {INTERVAL}s (TRY_STS={'on' if TRY_STS else 'off'})")
    while True:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        status, ak, msg = resolve_creds()
        if status == "ok":
            line = f"{ts}  creds resolved: {ak}"
            if TRY_STS:
                line += f"  |  {try_sts(ak)}"
            print(line, flush=True)
        else:
            print(f"{ts}  {status}: {msg}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
