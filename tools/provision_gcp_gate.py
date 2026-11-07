"""Provision the two distinct Google Cloud Gate capabilities for a paired host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from install_aws_gate import parse_env_file


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def private_json(path, payload):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")


def provision(args):
    url = urlsplit(args.url)
    if url.scheme != "https" or not url.hostname or url.netloc != url.hostname or url.path not in ("", "/") or url.query or url.fragment:
        raise SystemExit("Expected the broker HTTPS base URL")
    row_key = args.row_key
    if row_key is None:
        bearer = parse_env_file(args.aws_env.expanduser()).get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
        if not bearer:
            raise SystemExit("AWS Gate host bearer is missing")
        row_key = digest(bearer)
    if not re.fullmatch(r"[0-9a-f]{64}", row_key):
        raise SystemExit("Expected the paired AWS host row key")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,221}[a-z0-9]", args.bucket):
        raise SystemExit("Expected the Cloud Storage bucket name")

    endpoint = args.url.rstrip("/")
    token_url = f"{endpoint}/hosts/{row_key}/token"
    output = args.output.expanduser()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    adc_file = output / "credentials.json"
    pair_file = output / "pair.json"
    if not adc_file.exists():
        private_json(adc_file, {
            "type": "external_account_authorized_user",
            "token_url": token_url,
            "refresh_token": secrets.token_hex(32),
            "client_id": "phone-cloud-gate",
            "client_secret": "public-client",
        })
    if not pair_file.exists():
        private_json(pair_file, {
            "gcpUrl": endpoint,
            "gcpControllerToken": secrets.token_hex(32),
        })
    adc = json.loads(adc_file.read_text(encoding="utf-8"))
    pairing = json.loads(pair_file.read_text(encoding="utf-8"))
    if adc["token_url"] != token_url or pairing["gcpUrl"] != endpoint:
        raise SystemExit("Output directory is already bound to another broker or host")

    gcloud = shutil.which("gcloud.cmd" if os.name == "nt" else "gcloud")
    if not gcloud:
        raise SystemExit("gcloud is required to provision the host")
    destination = f"gs://{args.bucket}/hosts/{row_key}.json"
    row = {
        "host_hash": digest(adc["refresh_token"]),
        "controller_hash": digest(pairing["gcpControllerToken"]),
        "expires_at": 0,
    }
    result = subprocess.run(
        [gcloud, "storage", "cp", "--if-generation-match=0", "--content-type=application/json", "-", destination],
        input=json.dumps(row), text=True, capture_output=True,
    )
    if result.returncode:
        existing = subprocess.run([gcloud, "storage", "cat", destination], text=True, capture_output=True)
        if existing.returncode:
            raise SystemExit(f"Could not register host: {result.stderr.strip()}")
        current = json.loads(existing.stdout)
        if any(current.get(key) != row[key] for key in ("host_hash", "controller_hash")):
            raise SystemExit("Host is already registered with different credentials")
    print(f"Registered host. Private files: {adc_file} and {pair_file}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--aws-env", type=Path, default=Path("~/.config/aws-gate/env"))
    parser.add_argument("--row-key")
    provision(parser.parse_args())


if __name__ == "__main__":
    main()
