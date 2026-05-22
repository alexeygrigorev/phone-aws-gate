"""Small local STS stand-in for Docker e2e tests.

It implements enough of the AWS Query protocol for boto3 AssumeRole and
GetCallerIdentity. This keeps the test fully local while exercising the same
SDK calls the real Lambda/server use.
"""

from __future__ import annotations

import html
import time
import urllib.parse

from fastapi import FastAPI, Request, Response


app = FastAPI(title="fake STS")


@app.post("/")
async def sts(request: Request) -> Response:
    form = urllib.parse.parse_qs((await request.body()).decode("utf-8"))
    action = (form.get("Action") or [""])[0]
    if action == "AssumeRole":
        return xml(_assume_role(form))
    if action == "GetCallerIdentity":
        return xml(_get_caller_identity())
    return xml(_error(action), status_code=400)


def xml(body: str, status_code: int = 200) -> Response:
    return Response(body, status_code=status_code, media_type="text/xml")


def _assume_role(form: dict[str, list[str]]) -> str:
    role_arn = html.escape((form.get("RoleArn") or ["arn:aws:iam::000000000000:role/fake"])[0])
    session = html.escape((form.get("RoleSessionName") or ["aws-gate-local"])[0])
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 900))
    return f"""<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <AssumeRoleResult>
    <Credentials>
      <AccessKeyId>ASIAFAKELOCALSTS</AccessKeyId>
      <SecretAccessKey>fake-secret-local-sts</SecretAccessKey>
      <SessionToken>fake-session-token-local-sts</SessionToken>
      <Expiration>{expiration}</Expiration>
    </Credentials>
    <AssumedRoleUser>
      <Arn>{role_arn}/{session}</Arn>
      <AssumedRoleId>AROAFAKE:{session}</AssumedRoleId>
    </AssumedRoleUser>
  </AssumeRoleResult>
  <ResponseMetadata><RequestId>fake-request</RequestId></ResponseMetadata>
</AssumeRoleResponse>"""


def _get_caller_identity() -> str:
    return """<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult>
    <Arn>arn:aws:sts::000000000000:assumed-role/phone-aws-sandbox-role/local-e2e</Arn>
    <UserId>AROAFAKE:local-e2e</UserId>
    <Account>000000000000</Account>
  </GetCallerIdentityResult>
  <ResponseMetadata><RequestId>fake-request</RequestId></ResponseMetadata>
</GetCallerIdentityResponse>"""


def _error(action: str) -> str:
    escaped = html.escape(action)
    return f"""<ErrorResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <Error><Type>Sender</Type><Code>InvalidAction</Code><Message>Unsupported action: {escaped}</Message></Error>
  <RequestId>fake-request</RequestId>
</ErrorResponse>"""
