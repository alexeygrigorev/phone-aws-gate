"""Install and use AWS Gate / Phone Gate as a phone-approved credential and resource provider.

This intentionally does not modify shell startup files. It writes:

- ~/.config/aws-gate/env: the Lambda URL + bearer token used by AWS Gate
- ~/.aws/config: a default profile with credential_process

And provides CLI commands for agents to request and check phone approvals:
- request: submit a pending request (who asks, for what resource, why, for how long)
- status: check a request's state (pending, approved, denied, expired)
- check: check whether a resource/scope grant is currently open
- sms-heartbeat / sms-push / sms-poll: phone-gated SMS code relay
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
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_RESOURCES = ("aws-sandbox", "aws-main", "browser", "sms")
DEFAULT_SCOPES = {
    "aws-sandbox": "sandbox",
    "aws-main": "main",
    "browser": "desktop",
    "sms": "login",
}


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


def _resolve_gate_env(env_arg: str) -> tuple[str, str]:
    path = Path(env_arg).expanduser()
    if not path.exists():
        fallback = Path("/home/alexey/.config/aws-gate/env")
        if fallback.exists():
            path = fallback
    values = parse_env_file(path)
    url = (
        os.environ.get("PHONE_GATE_URL")
        or os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
        or values.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
        or ""
    ).strip()
    token = (
        os.environ.get("PHONE_GATE_TOKEN")
        or os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
        or values.get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
        or ""
    ).strip()
    if not url or not token:
        raise SystemExit(f"Missing AWS_CONTAINER_CREDENTIALS_FULL_URI or AWS_CONTAINER_AUTHORIZATION_TOKEN in {path}")
    return url.rstrip("/"), token


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

    config["profile main"] = {
        "region": region,
        "credential_process": f"{credential_command} --account main",
    }

    with path.open("w", encoding="utf-8") as f:
        config.write(f)
    path.chmod(0o600)
    return backup


def install(args: argparse.Namespace) -> int:
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


def _error_reason(error: urllib.error.HTTPError) -> str:
    """Short vendor reason (e.g. "Gate closed"); the vendor error body carries no secrets."""
    try:
        text = error.read(200).decode("utf-8", "replace")
    except Exception:
        return ""
    return " ".join(text.split())[:100]


def credential_process(args: argparse.Namespace) -> int:
    values = parse_env_file(Path(args.env).expanduser())
    url = values["AWS_CONTAINER_CREDENTIALS_FULL_URI"]
    token = values["AWS_CONTAINER_AUTHORIZATION_TOKEN"]

    if args.account == "main":
        url = f"{url.rstrip('/')}/main"
    request = urllib.request.Request(url, headers={"Authorization": token})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        reason = _error_reason(e)
        suffix = f" ({reason})" if reason else ""
        print(f"AWS Gate is closed or denied: HTTP {e.code}{suffix}", file=sys.stderr)
        return 1

    if args.account == "main" and payload.get("Account") != "main":
        print("AWS Gate vendor did not return a MAIN session", file=sys.stderr)
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


def _format_duration(ttl_s: int) -> str:
    if ttl_s % 3600 == 0:
        h = ttl_s // 3600
        return f"{h}h"
    if ttl_s % 60 == 0:
        m = ttl_s // 60
        return f"{m}m"
    return f"{ttl_s}s"


def _notify_phone(req_obj: dict, gate_token: str = "", pushed_by_vendor: bool = False) -> None:
    """Register request with tools.dtcdev.click/approve; notify the owner's phone.

    The vendor Lambda pushes the owner notification itself for every created
    request. The direct Telegram send here is only a fallback for older vendor
    deployments without push (`notified` missing/false), so the phone never
    receives the same request twice from two different bots.
    """
    notify_url = os.environ.get("PHONE_GATE_NOTIFY_URL", "https://tools.dtcdev.click/api/phone-gate/requests")
    auth_token = gate_token or os.environ.get("DTC_TOOLS_SECRET", "")
    if not auth_token:
        for candidate in (Path.home() / ".env", Path("/home/alexey/.env")):
            if candidate.exists():
                env_vals = parse_env_file(candidate)
                auth_token = env_vals.get("DTC_TOOLS_SECRET", "")
                if auth_token:
                    break
    if notify_url and auth_token:
        try:
            data = json.dumps(req_obj).encode("utf-8")
            http_req = urllib.request.Request(
                notify_url,
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(http_req, timeout=5.0):
                pass
        except Exception:
            pass

    if pushed_by_vendor:
        return

    # Fallback: direct Telegram notification to Alexey's phone if bot token is configured on host
    # Deduplicate by (requester, resource, scope) within 15 minutes so retries never spam the phone.
    dedup_file = Path("/home/alexey/.config/aws-gate/notify-dedup.json")
    dedup_key = f"{req_obj.get('requester','')}:{req_obj.get('resource','')}:{req_obj.get('scope','')}"
    now_ts = int(time.time())
    try:
        dedup = json.loads(dedup_file.read_text(encoding="utf-8")) if dedup_file.exists() else {}
    except Exception:
        dedup = {}
    if int(dedup.get(dedup_key, 0)) > now_ts - 900:
        return
    for tg_env in (Path("/home/alexey/git/personal-life-agent/.env"), Path("/home/alexey/git/telegram-writing-assistant/.env")):
        if tg_env.exists():
            vals = parse_env_file(tg_env)
            bot_token = vals.get("TELEGRAM_TOKEN") or vals.get("TELEGRAM_BOT_API_KEY") or ""
            chat_id = (vals.get("ALLOWED_USERS") or vals.get("TELEGRAM_CHAT_ID") or "").split(",")[0].strip()
            if bot_token and chat_id:
                req_id = req_obj.get("id", "")
                requester = req_obj.get("requester", "agent")
                resource = req_obj.get("resource", "")
                scope = req_obj.get("scope", "")
                reason = req_obj.get("reason", "")
                ttl_str = _format_duration(int(req_obj.get("ttl_s", 3600)))
                approve_url = f"https://tools.dtcdev.click/approve?id={urllib.parse.quote(str(req_id))}"
                text = (
                    f"Phone Approval Request ({req_id})\n"
                    f"• Who asks: {requester}\n"
                    f"• Resource: {resource} ({scope})\n"
                    f"• Why: {reason}\n"
                    f"• Duration: {ttl_str}\n\n"
                    f"Tap Approve or Deny in the Cloud Gate phone app, or open on phone:\n{approve_url}"
                )
                try:
                    tg_data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
                    tg_req = urllib.request.Request(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        data=tg_data,
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(tg_req, timeout=5.0):
                        dedup[dedup_key] = now_ts
                        dedup_file.write_text(json.dumps(dedup), encoding="utf-8")
                        break
                except Exception:
                    pass


def _vendor_http(
    base_url: str,
    token: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        reason = _error_reason(e)
        raise SystemExit(f"phone-aws-gate HTTP {e.code}: {reason}") from e


def _fetch_request_status(url: str, token: str, req_id: str, timeout: float = 10.0) -> dict:
    cur = _vendor_http(url, token, "GET", f"/requests/{req_id}", timeout=timeout)
    if cur.get("state") == "pending":
        tools_base = os.environ.get("TOOLS_ORIGIN", "https://tools.dtcdev.click").rstrip("/")
        try:
            req = urllib.request.Request(
                f"{tools_base}/api/phone-gate/requests/{urllib.parse.quote(str(req_id))}",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                tools_cur = json.loads(resp.read().decode("utf-8"))
                if tools_cur.get("state") in ("approved", "denied"):
                    cur["state"] = tools_cur["state"]
        except Exception:
            pass
    return cur


def cmd_request(args: argparse.Namespace) -> int:
    url, token = _resolve_gate_env(args.env_file)
    scope = args.scope or DEFAULT_SCOPES.get(args.resource, "default")
    req_obj = _vendor_http(
        url,
        token,
        "POST",
        "/requests",
        {
            "requester": args.requester,
            "resource": args.resource,
            "scope": scope,
            "reason": args.reason,
            "ttl_s": args.ttl,
        },
        timeout=args.timeout,
    )
    req_obj["approve_url"] = f"https://tools.dtcdev.click/approve?id={urllib.parse.quote(str(req_obj['id']))}"
    if not args.no_notify:
        _notify_phone(req_obj, token, pushed_by_vendor=bool(req_obj.get("notified")))

    if not args.wait:
        print(json.dumps(req_obj, indent=2))
        return 0

    req_id = req_obj["id"]
    print(
        f"Waiting for phone approval of request {req_id} "
        f"({args.requester} -> {args.resource}:{scope} for {_format_duration(args.ttl)})...",
        file=sys.stderr,
    )
    deadline = time.time() + args.wait_timeout
    while time.time() < deadline:
        cur = _fetch_request_status(url, token, req_id, timeout=args.timeout)
        state = cur.get("state")
        if state == "approved":
            print(json.dumps(cur, indent=2))
            return 0
        if state in ("denied", "expired"):
            print(json.dumps(cur, indent=2), file=sys.stderr)
            return 2
        time.sleep(args.poll_interval)

    print(f"Timed out waiting for phone approval of request {req_id}", file=sys.stderr)
    return 3


def cmd_status(args: argparse.Namespace) -> int:
    url, token = _resolve_gate_env(args.env_file)
    res = _fetch_request_status(url, token, args.request_id, timeout=args.timeout)
    print(json.dumps(res, indent=2))
    return 0 if res.get("state") == "approved" else 2


def cmd_check(args: argparse.Namespace) -> int:
    url, token = _resolve_gate_env(args.env_file)
    scope = args.scope or DEFAULT_SCOPES.get(args.resource, "default")
    q = urllib.parse.urlencode({"resource": args.resource, "scope": scope})
    res = _vendor_http(url, token, "GET", f"/check?{q}", timeout=args.timeout)
    print(json.dumps(res, indent=2))
    return 0 if res.get("granted") else 2


def cmd_sms_poll(args: argparse.Namespace) -> int:
    url, token = _resolve_gate_env(args.env_file)
    q = urllib.parse.urlencode({"scope": args.scope})
    res = _vendor_http(url, token, "GET", f"/sms/poll?{q}", timeout=args.timeout)
    print(json.dumps(res, indent=2))
    return 0 if res.get("code") else 2


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
    credential_parser.add_argument("--account", choices=("sandbox", "main"), default="sandbox")
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

    req_parser = sub.add_parser("request")
    req_parser.add_argument("--env-file", default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"))
    req_parser.add_argument("--requester", required=True, help="Who is asking (session or agent name)")
    req_parser.add_argument("--resource", required=True, choices=ALLOWED_RESOURCES, help="Resource requested")
    req_parser.add_argument("--scope", default="", help="Resource scope (e.g. desktop, sandbox, main, login)")
    req_parser.add_argument("--reason", required=True, help="Why the access is needed")
    req_parser.add_argument("--ttl", type=int, default=1800, help="Duration in seconds (60..86400)")
    req_parser.add_argument("--wait", action="store_true", help="Wait and poll until approved/denied/expired")
    req_parser.add_argument("--wait-timeout", type=float, default=900.0)
    req_parser.add_argument("--poll-interval", type=float, default=3.0)
    req_parser.add_argument("--no-notify", action="store_true")
    req_parser.add_argument("--timeout", type=float, default=10.0)
    req_parser.set_defaults(func=cmd_request)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("request_id")
    status_parser.add_argument("--env-file", default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"))
    status_parser.add_argument("--timeout", type=float, default=10.0)
    status_parser.set_defaults(func=cmd_status)

    check_parser = sub.add_parser("check")
    check_parser.add_argument("--resource", required=True, choices=ALLOWED_RESOURCES)
    check_parser.add_argument("--scope", default="")
    check_parser.add_argument("--env-file", default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"))
    check_parser.add_argument("--timeout", type=float, default=10.0)
    check_parser.set_defaults(func=cmd_check)

    sms_poll_parser = sub.add_parser("sms-poll")
    sms_poll_parser.add_argument("--scope", default="login")
    sms_poll_parser.add_argument("--env-file", default=os.environ.get("AWS_GATE_ENV_FILE", "~/.config/aws-gate/env"))
    sms_poll_parser.add_argument("--timeout", type=float, default=10.0)
    sms_poll_parser.set_defaults(func=cmd_sms_poll)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
