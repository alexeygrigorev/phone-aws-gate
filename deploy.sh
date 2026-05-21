#!/usr/bin/env bash
#
# Deploy or update the phone-aws-auth stack. The bearer token is generated
# locally and never enters CloudFormation — only its sha256 hash does.
#
# Re-running with the same $BEARER (or with the cached value below) is
# idempotent: the same hash goes in, the same row key comes back.
#
# Usage:
#   ./deploy.sh                  # generate a fresh bearer
#   BEARER='<existing-bearer>' ./deploy.sh   # reuse one (e.g. rotation)

set -euo pipefail

if [[ -f sandbox-account.env && -z "${SANDBOX_ASSUME_ROLE_ARN:-}" ]]; then
    set -a
    # shellcheck disable=SC1091
    source sandbox-account.env
    set +a
fi

if [[ -f .runtime/prod-test.env && -z "${BEARER:-}" ]]; then
    set -a
    # shellcheck disable=SC1091
    source .runtime/prod-test.env
    set +a
fi

STACK_NAME="${STACK_NAME:-phone-aws-auth}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"

# Generate a 32-byte (64 hex char) bearer if not provided.
BEARER="${BEARER:-$(openssl rand -hex 32)}"
if [[ "${#BEARER}" -lt 16 ]]; then
    echo "BEARER too short (need >=16 chars)" >&2
    exit 1
fi
SERVER_TOKEN_HASH="$(printf '%s' "$BEARER" | sha256sum | cut -d' ' -f1)"

umask 077
mkdir -p .runtime
cat > .runtime/prod-test.env <<EOF
BEARER=$BEARER
SERVER_TOKEN_HASH=$SERVER_TOKEN_HASH
EOF

echo "Deploying $STACK_NAME to $REGION ..."

parameter_overrides=("ServerTokenHash=$SERVER_TOKEN_HASH")
if [[ -n "${SANDBOX_ASSUME_ROLE_ARN:-}" ]]; then
    parameter_overrides+=("SandboxTargetRoleArn=$SANDBOX_ASSUME_ROLE_ARN")
    echo "Sandbox mode will target external role: $SANDBOX_ASSUME_ROLE_ARN"
else
    echo "Sandbox mode will target the in-account sandbox role."
fi

aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-file infra/template.yaml \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "${parameter_overrides[@]}"

echo
echo "=== Outputs ==="

# Fetch and pretty-print outputs.
mapfile -t outputs < <(
    aws cloudformation describe-stacks \
        --region "$REGION" \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' \
        --output text
)
declare -A out
for line in "${outputs[@]}"; do
    key="${line%%$'\t'*}"
    val="${line#*$'\t'}"
    out[$key]="$val"
done

cat <<EOF

Server bearer (write this in the server's env, then delete this line):
  AWS_CONTAINER_CREDENTIALS_FULL_URI=${out[VendorUrl]}
  AWS_CONTAINER_AUTHORIZATION_TOKEN=${BEARER}

Phone / CLI configuration:
  region:          ${REGION}
  table:           phone-aws-gate
  row key:         ${out[GateRowKey]}
  access key id:   ${out[ControllerAccessKeyId]}
  secret key:      ${out[ControllerSecretAccessKey]}

Target role ARNs:
  prod:    ${out[ProdRoleArn]}
  sandbox: ${out[SandboxRoleArn]}

To customise role permissions later:
  aws iam put-role-policy --role-name phone-aws-prod-role ...
  aws iam put-role-policy --role-name phone-aws-sandbox-role ...

To revoke phone access immediately:
  aws iam update-access-key \\
      --user-name phone-aws-controller \\
      --access-key-id ${out[ControllerAccessKeyId]} \\
      --status Inactive

EOF

# Render the pairing QR if uv + qrcode are available.
if command -v uv >/dev/null && [[ -f tools/pair_qr.py ]]; then
    echo "Pairing QR (scan with the phone in the Pair screen):"
    echo
    uv run --extra tools python -m tools.pair_qr \
        --region "$REGION" \
        --row-key "${out[GateRowKey]}" \
        --access-key-id "${out[ControllerAccessKeyId]}" \
        --secret-access-key "${out[ControllerSecretAccessKey]}" \
        || echo "  (QR render failed — re-run \`uv run python -m tools.pair_qr --json ...\` manually)"
fi
