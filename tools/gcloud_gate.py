"""Run gcloud with a fresh access token from a paired Google Cloud Gate."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def access_token(credentials):
    data = json.loads(credentials.read_text(encoding="utf-8"))
    url = urllib.parse.urlsplit(data["token_url"])
    if url.scheme != "https" or not url.hostname or url.netloc != url.hostname or url.query or url.fragment:
        raise ValueError("The gate token endpoint must use HTTPS")
    form = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": data["refresh_token"],
    }).encode()
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(urllib.request.Request(url.geturl(), form), timeout=30) as response:
        payload = json.loads(response.read(16384))
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or not isinstance(payload.get("expires_in"), int) or payload["expires_in"] <= 0:
        raise ValueError("Invalid gate token response")
    return token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--gcloud", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Specify a gcloud command after --")
    credentials = args.credentials.expanduser().resolve()
    try:
        token = access_token(credentials)
    except urllib.error.HTTPError as error:
        print(f"Google Cloud Gate denied token refresh (HTTP {error.code})", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        print("Google Cloud Gate token refresh failed", file=sys.stderr)
        return 1

    env = {
        **os.environ,
        "CLOUDSDK_AUTH_ACCESS_TOKEN": token,
        "CLOUDSDK_CORE_PROJECT": args.project,
        "GOOGLE_APPLICATION_CREDENTIALS": str(credentials),
        "GOOGLE_CLOUD_PROJECT": args.project,
    }
    return subprocess.call([args.gcloud, *command], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
