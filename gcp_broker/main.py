"""Google Cloud grant controller and short-lived OAuth token broker."""

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime

import google.auth
from flask import Flask, jsonify, request
from google.api_core.exceptions import GoogleAPICallError, NotFound, PreconditionFailed
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage
from requests import RequestException


CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
HOST_KEY = re.compile(r"[a-f0-9]{64}")
TOKEN_TTL = 900


def secret_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class GrantStore:
    def __init__(self, bucket_name):
        self.bucket = storage.Client().bucket(bucket_name)

    def read(self, host):
        blob = self.bucket.blob(f"hosts/{host}.json")
        try:
            blob.reload(timeout=5)
            data = blob.download_as_bytes(if_generation_match=blob.generation, timeout=5)
        except NotFound:
            return None, None
        return json.loads(data), blob.generation

    def write(self, host, data, generation):
        self.bucket.blob(f"hosts/{host}.json").upload_from_string(
            json.dumps(data), content_type="application/json",
            if_generation_match=generation, timeout=5,
        )


def mint_token(service_account, lifetime):
    credentials, _ = google.auth.default(scopes=[CLOUD_SCOPE])
    with AuthorizedSession(credentials) as session:
        response = session.post(
            f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{service_account}:generateAccessToken",
            json={"scope": [CLOUD_SCOPE], "lifetime": f"{lifetime}s"},
            timeout=7,
        )
        response.raise_for_status()
        return response.json()


def create_app(store=None, minter=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2048

    def grants():
        return store if store is not None else GrantStore(os.environ["GATE_BUCKET"])

    def load(host, secret, key):
        if not HOST_KEY.fullmatch(host) or not HOST_KEY.fullmatch(secret):
            return None, None
        row, generation = grants().read(host)
        if row is None or not hmac.compare_digest(row[key], secret_hash(secret)):
            return None, None
        return row, generation

    @app.after_request
    def no_store(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(PreconditionFailed)
    def conflict(_error):
        return jsonify(error="grant_changed_retry"), 409

    @app.errorhandler(GoogleAPICallError)
    @app.errorhandler(RequestException)
    def unavailable(error):
        if isinstance(error, GoogleAPICallError):
            app.logger.warning("Google Cloud Gate storage failure: %s %s", type(error).__name__, error.message)
        else:
            response = error.response
            app.logger.warning("Google Cloud Gate IAM request failed: %s", response.status_code if response is not None else type(error).__name__)
        return jsonify(error="temporarily_unavailable"), 503

    @app.route("/hosts/<host>/grant", methods=["GET", "PUT", "DELETE"])
    def grant(host):
        scheme, _, secret = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            return jsonify(error="forbidden"), 403
        row, generation = load(host, secret, "controller_hash")
        if row is None:
            return jsonify(error="forbidden"), 403
        now = int(time.time())
        if request.method == "GET":
            return jsonify(expires_at=row["expires_at"] if row["expires_at"] > now else 0)
        expires = 0
        if request.method == "PUT":
            data = request.get_json(silent=True)
            duration = data.get("duration_minutes") if isinstance(data, dict) else None
            if type(duration) is not int or not 1 <= duration <= 24 * 60:
                return jsonify(error="invalid_duration"), 400
            expires = now + duration * 60
        grants().write(host, {**row, "expires_at": expires}, generation)
        return jsonify(expires_at=expires)

    @app.post("/hosts/<host>/token")
    def token(host):
        if request.form.get("grant_type") != "refresh_token":
            return jsonify(error="unsupported_grant_type"), 400
        row, generation = load(host, request.form.get("refresh_token", ""), "host_hash")
        if row is None:
            return jsonify(error="invalid_grant"), 403
        lifetime = min(TOKEN_TTL, row["expires_at"] - int(time.time()) - 5)
        if lifetime <= 0:
            return jsonify(error="invalid_grant"), 403
        minted = minter(lifetime) if minter else mint_token(os.environ["GATE_SERVICE_ACCOUNT"], lifetime)
        _, latest = grants().read(host)
        if latest != generation or row["expires_at"] <= time.time():
            return jsonify(error="invalid_grant"), 403
        expires = datetime.fromisoformat(minted["expireTime"]).timestamp()
        remaining = int(expires - time.time())
        if remaining <= 0 or expires > row["expires_at"]:
            return jsonify(error="invalid_grant"), 403
        return jsonify(access_token=minted["accessToken"], expires_in=remaining, token_type="Bearer")

    return app


app = create_app()
