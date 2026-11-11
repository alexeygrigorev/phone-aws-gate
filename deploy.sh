#!/usr/bin/env bash
#
# Deploy or update the AWS Gate stack. Host bearer tokens are generated
# separately by ./install-aws-gate-env.sh so each machine can have its own gate.

set -euo pipefail

STACK_NAME="${STACK_NAME:-phone-aws-auth}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-west-1}}"

umask 077
mkdir -p .runtime

# Owner push channel for new approval requests. Values are secrets and live in
# the gitignored .runtime/notify.env; they are passed as NoEcho parameters and
# are never printed or committed.
PARAM_OVERRIDES=()
if [[ -f .runtime/notify.env ]]; then
    # shellcheck disable=SC1091
    . ./.runtime/notify.env
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && PARAM_OVERRIDES+=(--parameter-overrides "TelegramBotToken=${TELEGRAM_BOT_TOKEN}" "TelegramChatId=${TELEGRAM_CHAT_ID:-}" "ApproveBaseUrl=${GATE_APPROVE_BASE_URL:-https://tools.dtcdev.click}")
fi

echo "Deploying $STACK_NAME to $REGION ..."

echo "Sandbox mode will target the sandbox role created by this stack."

aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-file infra/template.yaml \
    --capabilities CAPABILITY_NAMED_IAM \
    ${PARAM_OVERRIDES+"${PARAM_OVERRIDES[@]}"}

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

Server credential endpoint:
  AWS_CONTAINER_CREDENTIALS_FULL_URI=${out[VendorUrl]}

Phone / CLI configuration:
  region:          ${REGION}
  table:           phone-aws-gate
  access key id:   ${out[ControllerAccessKeyId]}
  secret key:      ${out[ControllerSecretAccessKey]}

Target role ARN:
  sandbox: ${out[SandboxRoleArn]}

To customise role permissions later:
  aws iam put-role-policy --role-name phone-aws-sandbox-role ...

To revoke phone access immediately:
  aws iam update-access-key \\
      --user-name phone-aws-controller \\
      --access-key-id ${out[ControllerAccessKeyId]} \\
      --status Inactive

EOF

cat > .runtime/controller.json <<EOF
{"region":"$REGION","table":"phone-aws-gate","vendorUrl":"${out[VendorUrl]}","accessKeyId":"${out[ControllerAccessKeyId]}","secretAccessKey":"${out[ControllerSecretAccessKey]}"}
EOF

echo "Next on each host:"
echo "  ./install-aws-gate-env.sh"
echo "  ./pair-qr.sh"
