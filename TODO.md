# TODO

## Done

- Fix Android biometric plumbing so `BiometricPrompt` has a `FragmentActivity` host.
- Fail closed if paired-mode biometric prompting is unavailable.
- Disable Start/Stop until the app has successfully read gate status.
- Add Android JVM tests for pairing JSON parsing and gate-action enablement.
- Add Makefile targets for Android build/install/launch and pairing QR regeneration.
- Document the real-AWS emulator test flow.
- Show the selected auto-close TTL in the Android interface.

## Next

- Confirm provided AWS credentials can create IAM/CloudFormation resources.
- Deploy the sandbox-only stack using `.env` credentials.
- Generate pairing payload/QR for the emulator.
- Run Docker test-server against the real vendor URL.
- Test Start sandbox, then Stop, against the real stack.

## Backlog

- Show an explicit "Extend" prompt/action when an open gate is near its TTL expiry so the session can be prolonged before interruption.
- Persist a preferred default auto-close TTL instead of always defaulting to 1h.
- Add Android integration tests for `GateClient` status/error mapping against DDB Local.
- Add an emulator/UI test for biometric-required gate operations.
- Decide whether role permissions should be inline in `infra/template.yaml` or external files under `infra/permissions/`; update code/docs to match.
- Remove drift between the tested Python vendor handler and the inline CloudFormation Lambda code.
- Clean stale README details: `loop.py` vs `loop.sh`, `pair_qr.py` vs `pair-qr.py`, visible paste flow, and direct-DynamoDB Stop wording.
- Consider an operator-only instant-kill script if immediate STS-session revocation remains in scope.
