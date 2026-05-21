"""Install AWS Gate as an AWS shared-config credential provider.

This intentionally does not modify shell startup files. It writes:

- ~/.config/aws-gate/env: the Lambda URL + bearer token used by AWS Gate
- ~/.aws/config: a default profile with credential_process

After that, AWS CLI and SDKs that support AWS shared config can resolve
credentials without depending on .bashrc or per-shell exports.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("unset "):
            continue
        if line.startswith("export "):
            parts = shlex.split(line)
            assignments = parts[1:]
        else:
            assignments = [line]
        for item in assignments:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            values[key] = value
    return values


def cloudformation_vendor_url(stack_name: str, region: str) -> str:
    cmd = [
        "aws",
        "cloudformation",
        "describe-stacks",
        "--region",
        region,
        "--stack-name",
        stack_name,
        "--query",
        "Stacks[0].Outputs[?OutputKey=='VendorUrl'].OutputValue | [0]",
        "--output",
        "text",
    ]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    value = result.stdout.strip()
    if not value or value == "None":
        raise SystemExit(f"Could not find VendorUrl output for stack {stack_name!r} in {region}")
    return value


def cloudformation_outputs(stack_name: str, region: str) -> dict[str, str]:
    cmd = [
        "aws",
        "cloudformation",
        "describe-stacks",
        "--region",
        region,
        "--stack-name",
        stack_name,
        "--query",
        "Stacks[0].Outputs",
        "--output",
        "json",
    ]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return {item["OutputKey"]: item["OutputValue"] for item in json.loads(result.stdout)}


def remove_bashrc_block(path: Path) -> bool:
    if not path.exists():
        return False
    begin = "# >>> aws-gate >>>"
    end = "# <<< aws-gate <<<"
    text = path.read_text(encoding="utf-8")
    start = text.find(begin)
    finish = text.find(end)
    if start == -1 or finish == -1 or finish < start:
        return False
    finish += len(end)
    path.write_text(text[:start].rstrip() + "\n" + text[finish:].lstrip(), encoding="utf-8")
    return True


def write_gate_env(path: Path, *, region: str, vendor_url: str, bearer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        path.write_text(
            "\n".join(
                [
                    "# AWS Gate credential provider config.",
                    "# This file contains the server bearer token. Keep mode 0600.",
                    f'export AWS_DEFAULT_REGION="{region}"',
                    f'export AWS_REGION="{region}"',
                    f'export AWS_CONTAINER_CREDENTIALS_FULL_URI="{vendor_url}"',
                    f'export AWS_CONTAINER_AUTHORIZATION_TOKEN="{bearer}"',
                    "",
                ],
            ),
            encoding="utf-8",
        )
    finally:
        os.umask(old_umask)
    path.chmod(0o600)


def update_aws_config(path: Path, *, region: str, credential_command: str) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None

    config = configparser.RawConfigParser()
    config.optionxform = str
    if path.exists():
        backup = path.with_name(f"{path.name}.backup.{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(path, backup)
        config.read(path)

    if "default" not in config:
        config["default"] = {}
    config["default"]["region"] = region
    config["default"]["credential_process"] = credential_command

    with path.open("w", encoding="utf-8") as f:
        config.write(f)
    path.chmod(0o600)
    return backup


def install(args: argparse.Namespace) -> int:
    runtime_env = Path(args.runtime_env).expanduser()
    gate_env = Path(args.env_file).expanduser()
    aws_config = Path(args.aws_config).expanduser()

    existing_gate_values = parse_env_file(gate_env)
    controller_values = read_controller_file(args.controller_file)

    bearer = existing_gate_values.get("AWS_CONTAINER_AUTHORIZATION_TOKEN") or secrets.token_hex(32)

    vendor_url = (
        existing_gate_values.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
        or controller_values.get("vendorUrl")
        or controller_values.get("VendorUrl")
    )
    if not vendor_url:
        vendor_url = cloudformation_vendor_url(args.stack_name, args.region)

    write_gate_env(gate_env, region=args.region, vendor_url=vendor_url, bearer=bearer)

    script = Path(__file__).resolve()
    credential_command = f"python3 {shlex.quote(str(script))} credential-process --env {shlex.quote(str(gate_env))}"
    backup = update_aws_config(aws_config, region=args.region, credential_command=credential_command)

    removed_bashrc = remove_bashrc_block(Path.home() / ".bashrc")

    print(f"Installed AWS Gate env file: {gate_env}")
    print(f"Host row key: {hashlib.sha256(bearer.encode('utf-8')).hexdigest()}")
    print(f"Configured AWS shared config: {aws_config}")
    print("Configured profile: default")
    if backup:
        print(f"Backed up previous AWS config: {backup}")
    if removed_bashrc:
        print("Removed previous aws-gate block from ~/.bashrc")
    print("No shell startup files are required.")
    return 0


def read_controller_file(path: str) -> dict[str, str]:
    controller_file = Path(path).expanduser()
    if not controller_file.exists():
        return {}
    data = json.loads(controller_file.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def controller_config(args: argparse.Namespace) -> dict[str, str]:
    values = read_controller_file(args.controller_file)
    if {"accessKeyId", "secretAccessKey"}.issubset(values):
        return values

    outputs = cloudformation_outputs(args.stack_name, args.region)
    return {
        "region": args.region,
        "table": "phone-aws-gate",
        "vendorUrl": outputs["VendorUrl"],
        "accessKeyId": outputs["ControllerAccessKeyId"],
        "secretAccessKey": outputs["ControllerSecretAccessKey"],
    }


def pairing_payload(args: argparse.Namespace) -> dict[str, str]:
    gate_values = parse_env_file(Path(args.env_file).expanduser())
    bearer = gate_values.get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
    if not bearer:
        raise SystemExit(f"AWS_CONTAINER_AUTHORIZATION_TOKEN is missing from {args.env_file}")

    controller = controller_config(args)
    name = args.name or socket.gethostname()
    return {
        "name": name,
        "region": controller.get("region", args.region),
        "table": controller.get("table", "phone-aws-gate"),
        "rowKey": hashlib.sha256(bearer.encode("utf-8")).hexdigest(),
        "accessKeyId": controller["accessKeyId"],
        "secretAccessKey": controller["secretAccessKey"],
    }


def pair_qr(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.pair_qr import render_qr

    payload_json = json.dumps(pairing_payload(args))
    if args.json:
        print(payload_json)
        return 0
    render_qr(payload_json)
    print(f"\nPayload size: {len(payload_json)} chars")
    print("Scan with AWS Gate: Pair -> Scan QR.")
    return 0


def credential_process(args: argparse.Namespace) -> int:
    values = parse_env_file(Path(args.env).expanduser())
    url = values["AWS_CONTAINER_CREDENTIALS_FULL_URI"]
    token = values["AWS_CONTAINER_AUTHORIZATION_TOKEN"]

    request = urllib.request.Request(url, headers={"Authorization": token})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"AWS Gate is closed or denied: HTTP {e.code}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "Version": 1,
                "AccessKeyId": payload["AccessKeyId"],
                "SecretAccessKey": payload["SecretAccessKey"],
                "SessionToken": payload["Token"],
                "Expiration": payload["Expiration"],
            },
        ),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--stack-name", default=os.environ.get("STACK_NAME", "phone-aws-auth"))
    install_parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1",
    )
    install_parser.add_argument("--runtime-env", default=os.environ.get("RUNTIME_ENV", ".runtime/prod-test.env"))
    install_parser.add_argument("--controller-file", default=".runtime/controller.json")
    install_parser.add_argument(
        "--env-file",
        default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"),
    )
    install_parser.add_argument("--aws-config", default=os.environ.get("AWS_CONFIG_FILE", "~/.aws/config"))
    install_parser.set_defaults(func=install)

    credential_parser = sub.add_parser("credential-process")
    credential_parser.add_argument("--env", required=True)
    credential_parser.add_argument("--timeout", type=float, default=10.0)
    credential_parser.set_defaults(func=credential_process)

    pair_parser = sub.add_parser("pair-qr")
    pair_parser.add_argument("--name", default=None)
    pair_parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1",
    )
    pair_parser.add_argument("--stack-name", default=os.environ.get("STACK_NAME", "phone-aws-auth"))
    pair_parser.add_argument("--controller-file", default=".runtime/controller.json")
    pair_parser.add_argument("--env-file", default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"))
    pair_parser.add_argument("--json", action="store_true")
    pair_parser.set_defaults(func=pair_qr)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
