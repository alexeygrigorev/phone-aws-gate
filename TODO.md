# TODO

## Done

- Fix Android biometric plumbing so `BiometricPrompt` has a `FragmentActivity` host.
- Fail closed if paired-mode biometric prompting is unavailable.
- Disable Start/Stop until the app has successfully read gate status.
- Add Android JVM tests for pairing JSON parsing and gate-action enablement.
- Add Makefile targets for Android build/install/launch and pairing QR regeneration.
- Document the real-AWS emulator test flow.
- Show the selected auto-close TTL in the Android interface.
- Generate pairing payload/QR for the emulator.
- Run Docker test-server against the local vendor URL through the emulator E2E.
- Show an explicit "Extend" action when an open gate can be prolonged before interruption.
- Confirm provided AWS credentials can create IAM/CloudFormation resources.
- Deploy the sandbox-only stack using `.env` credentials.
- Test Start sandbox, then Stop, against the real stack.

## Backlog

- [x] Remove drift risk between the tested Python vendor handler and the CloudFormation Lambda code by directly testing the inline handler.
- [x] Add Android `GateClient` status mapping coverage; live DDB Local behavior is covered by the emulator E2E.
- [x] Add an emulator/UI test for biometric-required gate operations.
- [x] Decide whether role permissions stay inline in `infra/template.yaml` or move under `infra/permissions/`; keep them inline and document the reason.
- [x] Clean stale README details: command names, visible paste flow, and Stop/biometric wording.
- [x] Persist a preferred default auto-close TTL instead of always defaulting to 1h.

## Later

- Consider an operator-only instant-kill script if immediate STS-session revocation remains in scope.
