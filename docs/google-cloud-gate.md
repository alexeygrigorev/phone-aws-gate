# Google Cloud access

AWS Gate pairs each computer with an AWS row and, optionally, a Google Cloud grant. The app lists AWS Sandbox, AWS Main and Google Cloud for each computer. Select a computer, choose the accounts and TTL, then apply with biometrics. Stop closes its grants. Each cloud reports its own status if the other is unavailable.

The Google Cloud broker runs on Cloud Run with a dedicated service account. It reads and writes grants in a private Cloud Storage bucket and uses the IAM Credentials API to issue access tokens for a separate target service account. AWS credentials cannot update the Google Cloud grants. The computer holds a host capability and the phone holds a separate controller capability. Neither capability is a Google account refresh token or service account key.

Tokens last at most 15 minutes and expire by the end of their grant. Stop denies fresh requests. A token already issued remains usable until its expiry.

## Deploy the broker

1. Enable Cloud Run, Cloud Build, Artifact Registry and IAM Service Account Credentials in the control project.
2. Create a private regional bucket with uniform bucket-level access and public access prevention. Grant the broker service account `roles/storage.objectUser` on this bucket.
3. Grant the broker `roles/iam.serviceAccountTokenCreator` on the target service account only. Grant the target only the roles that paired computers may receive. Keep administrative access to the broker, bucket and service accounts outside the target role.
4. Deploy `gcp_broker/` to Cloud Run with the broker service account and set `GATE_BUCKET` and `GATE_SERVICE_ACCOUNT`. Allow unauthenticated requests at the Cloud Run ingress so the app and SDK can reach the service. The service authenticates every grant and token request itself.

## Pair a computer

Use the existing AWS Gate host pairing and add its Google Cloud capability. On the provisioning machine, run:

```sh
python tools/provision_gcp_gate.py --url "$GATE_URL" --bucket "$GATE_BUCKET" \
    --row-key "$AWS_GATE_ROW_KEY" --output .runtime/gcp/hostname
```

Omit `--row-key` if the provisioning machine is the paired host and its AWS Gate env is at `~/.config/aws-gate/env`. Keep the output directory private so a retry can reuse the same two capabilities. Install `credentials.json` on the paired computer with owner-only permissions. Use `pair.json` when rendering the existing host's pairing QR and re-pair to update its entry.

```sh
./pair-qr.sh --name hostname --gcp-pairing .runtime/gcp/hostname/pair.json
```

Set the project's name and point both credential consumers at the private file in the gated environment:

```sh
export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="$HOME/.config/gcp-gate/credentials.json"
export GOOGLE_APPLICATION_CREDENTIALS="$CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"
export CLOUDSDK_CORE_PROJECT=dtcdev-click
export GOOGLE_CLOUD_PROJECT=dtcdev-click
gcloud compute instances list
```

Use the corresponding environment variables in PowerShell. The ADC file uses the external-account authorized-user format supported by gcloud and Python google-auth. SDK support depends on the language and library version. Remove any higher-priority CLI credentials from the gated environment. A separate owner login on the same OS account remains independently usable.

Run a read-only command with the gate open, then start a fresh CLI process after Stop and verify that token refresh is denied.
