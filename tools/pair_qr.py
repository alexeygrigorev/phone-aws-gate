"""Render the phone-pairing JSON as a QR code on stdout.

Called by deploy.sh after a successful stack deployment. Also useful on
its own for re-pairing without redeploying:

    uv run -m tools.pair_qr \\
        --region eu-west-1 \\
        --row-key <hash> \\
        --access-key-id <AKID> \\
        --secret-access-key <SK>

Use --json to emit just the JSON (no QR) — handy when the Android emulator
doesn't have a working camera and you want to paste into the Pair screen.
"""

from __future__ import annotations

import argparse
import json
import sys


def build_payload(args: argparse.Namespace) -> dict:
    return {
        "name": args.name,
        "region": args.region,
        "table": args.table,
        "rowKey": args.row_key,
        "accessKeyId": args.access_key_id,
        "secretAccessKey": args.secret_access_key,
    }


def render_qr(payload_json: str) -> None:
    try:
        import qrcode
    except ImportError:
        print(
            "qrcode is not installed. Install with: uv sync --extra tools",
            file=sys.stderr,
        )
        sys.exit(1)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(payload_json)
    qr.make(fit=True)
    qr.print_ascii(invert=True, tty=sys.stdout.isatty())


def main() -> None:
    p = argparse.ArgumentParser(
        description="Render the phone-pairing JSON payload as a QR (or print it).",
    )
    p.add_argument("--region", default="eu-west-1")
    p.add_argument("--name", default="host")
    p.add_argument("--table", default="phone-aws-gate")
    p.add_argument("--row-key", required=True,
                   help="sha256 of the server bearer (64 hex chars)")
    p.add_argument("--access-key-id", required=True,
                   help="IAM access key ID for phone-aws-controller")
    p.add_argument("--secret-access-key", required=True,
                   help="IAM secret access key for phone-aws-controller")
    p.add_argument("--json", action="store_true",
                   help="Print the JSON payload only — no QR")
    args = p.parse_args()

    payload_json = json.dumps(build_payload(args))

    if args.json:
        print(payload_json)
        return

    render_qr(payload_json)
    print(f"\nPayload size: {len(payload_json)} chars")
    print("Scan with the phone in the Pair screen, or pass --json to get the raw payload.")


if __name__ == "__main__":
    main()
