"""Local end-to-end test for two registered hosts.

This test is fully local and reproducible:

1. Starts DynamoDB Local, the local vendor Lambda shim, and a local fake STS.
2. Builds/installs the debug Android APK on an active emulator/device.
3. Registers two host payloads through the app's debug pairing hook.
4. Uses the emulator UI to select host A and tap Start.
5. Runs two Docker "server" containers with different bearer tokens.
6. Asserts host A receives credentials and GetCallerIdentity works via local fake STS.
7. Asserts host B is refused by the local Lambda with 403.
8. Uses the emulator UI to stop host A, select host B, and tap Start.
9. Asserts the same two running containers flip: A is refused and B gets identity.

The server containers use the normal AWS SDK credential provider chain. The
only local-test trick is endpoint configuration: the container credentials URL
points at the local Lambda shim, and STS points at the local fake STS shim.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from tools.phone_client import GateClient


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "phone-aws-auth-e2e")
COMPOSE = ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", "docker/docker-compose.yml"]
PKG = "com.alexeygrigorev.phoneawsauth"
ACTIVITY = f"{PKG}/.MainActivity"
REGION = "eu-west-1"
TABLE = "phone-aws-gate"
HOST_DDB_ENDPOINT = "http://localhost:18000"
EMULATOR_DDB_ENDPOINT = "http://10.0.2.2:18000"
VENDOR_URL_IN_SERVER = "http://127.0.0.1:8002/"
STS_URL_IN_SERVER = "http://fake-sts:4592/"


@dataclass(frozen=True)
class Host:
    name: str
    bearer: str

    @property
    def row_key(self) -> str:
        return hashlib.sha256(self.bearer.encode("utf-8")).hexdigest()

    def payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "region": REGION,
            "table": TABLE,
            "rowKey": self.row_key,
            "accessKeyId": "local",
            "secretAccessKey": "local",
            "ddbEndpoint": EMULATOR_DDB_ENDPOINT,
        }


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True, capture: bool = False) -> str:
    print("+", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout or ""


def run_completed(cmd: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def adb(args: list[str], *, capture: bool = False, check: bool = True) -> str:
    adb_bin = os.environ.get("ADB", str(Path.home() / "Android/Sdk/platform-tools/adb"))
    if not Path(adb_bin).exists():
        adb_bin = "adb"
    return run([adb_bin, *args], capture=capture, check=check)


def wait_for_adb() -> None:
    adb(["wait-for-device"])
    out = adb(["devices"], capture=True)
    lines = [line for line in out.splitlines() if line.endswith("\tdevice")]
    if not lines:
        raise SystemExit("No active adb device/emulator found")


def wait_for_emulator_host_port(port: int, *, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = adb(
            ["shell", f"toybox nc -z -w 2 10.0.2.2 {port}; echo nc_rc=$?"],
            capture=True,
            check=False,
        )
        if "nc_rc=0" in last:
            return
        time.sleep(1)
    raise AssertionError(f"Emulator could not reach host port {port} via 10.0.2.2\n{last}")


def build_and_install_app() -> None:
    run(["./gradlew", "assembleDebug", "--no-daemon"], cwd=ROOT / "android")
    adb(["install", "-r", "android/app/build/outputs/apk/debug/app-debug.apk"])
    adb(["shell", "pm", "clear", PKG])


def start_local_stack() -> str:
    run([*COMPOSE, "up", "-d", "--build", "dynamodb-local", "bootstrap", "fake-sts", "vendor"])
    vendor_id = run([*COMPOSE, "ps", "-q", "vendor"], capture=True).strip()
    if not vendor_id:
        raise SystemExit("Could not find local vendor container id")
    return vendor_id


def stop_local_stack() -> None:
    run([*COMPOSE, "down"], check=False)


def client(host: Host) -> GateClient:
    return GateClient(
        row_key=host.row_key,
        table_name=TABLE,
        region=REGION,
        endpoint_url=HOST_DDB_ENDPOINT,
    )


def stop_gate(host: Host) -> None:
    client(host).stop()


def status(host: Host):
    return client(host).status()


def register_host(host: Host, *, skip_biometric: bool = True) -> None:
    payload = json.dumps(host.payload(), separators=(",", ":"))
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    adb(["shell", "am", "force-stop", PKG])
    cmd = [
        "shell",
        "am",
        "start",
        "-n",
        ACTIVITY,
    ]
    if skip_biometric:
        cmd.extend(["--ez", "skip_biometric", "true"])
    cmd.extend(["--es", "pairing_json_b64", encoded])
    adb(cmd)
    time.sleep(1)


def register_hosts(*hosts: Host, skip_biometric: bool = True) -> None:
    payloads = [host.payload() for host in hosts]
    encoded = base64.b64encode(json.dumps(payloads, separators=(",", ":")).encode("utf-8")).decode("ascii")
    adb(["shell", "am", "force-stop", PKG])
    cmd = [
        "shell",
        "am",
        "start",
        "-n",
        ACTIVITY,
    ]
    if skip_biometric:
        cmd.extend(["--ez", "skip_biometric", "true"])
    cmd.extend(["--es", "pairing_jsons_b64", encoded])
    adb(cmd)
    time.sleep(1)


def dump_ui() -> str:
    deadline = time.time() + 15
    last = ""
    while time.time() < deadline:
        adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=False)
        dump = adb(["shell", "uiautomator", "dump", "/sdcard/aws-gate-window.xml"], capture=True, check=False)
        xml = adb(["exec-out", "cat", "/sdcard/aws-gate-window.xml"], capture=True, check=False)
        last = f"{dump}\n{xml}"
        if "<hierarchy" in xml:
            return xml
        time.sleep(0.5)
    raise AssertionError(f"Could not dump emulator UI\n{last}")


def node_bounds(node: ET.Element) -> tuple[int, int, int, int]:
    raw = node.attrib["bounds"]
    left_top, right_bottom = raw.split("][")
    x1, y1 = [int(x) for x in left_top.strip("[").split(",")]
    x2, y2 = [int(x) for x in right_bottom.strip("]").split(",")]
    return x1, y1, x2, y2


def tap_text(text: str, *, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_xml = ""
    while time.time() < deadline:
        last_xml = dump_ui()
        root = ET.fromstring(last_xml)
        for node in root.iter("node"):
            if node.attrib.get("text") == text:
                x1, y1, x2, y2 = node_bounds(node)
                adb(["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)])
                time.sleep(1)
                return
        time.sleep(0.5)
    raise AssertionError(f"Could not find UI text {text!r}\nLast UI:\n{last_xml}")


def assert_ui_contains(*texts: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    xml = ""
    while time.time() < deadline:
        xml = dump_ui()
        missing = [text for text in texts if text not in xml]
        if not missing:
            return
        time.sleep(0.5)
    raise AssertionError(f"UI did not contain {missing!r}\n{xml}")


def docker_image() -> str:
    return run(["docker", "build", "-q", "docker/test-server"], capture=True).strip()


def start_server_container(image: str, vendor_container: str, host: Host) -> str:
    name = f"aws-gate-e2e-{host.name}"
    run(["docker", "rm", "-f", name], check=False)
    run([
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        f"container:{vendor_container}",
        "-e",
        f"AWS_CONTAINER_CREDENTIALS_FULL_URI={VENDOR_URL_IN_SERVER}",
        "-e",
        f"AWS_CONTAINER_AUTHORIZATION_TOKEN={host.bearer}",
        "-e",
        f"STS_ENDPOINT_URL={STS_URL_IN_SERVER}",
        "-e",
        f"AWS_ENDPOINT_URL_STS={STS_URL_IN_SERVER}",
        "-e",
        f"AWS_ENDPOINT_URL={STS_URL_IN_SERVER}",
        "-e",
        "AWS_DEFAULT_REGION=eu-west-1",
        "-e",
        "INTERVAL_SECONDS=1",
        "-e",
        "TRY_STS=1",
        image,
    ])
    return name


def wait_for_log(container: str, needle: str, *, timeout: float = 45.0) -> str:
    deadline = time.time() + timeout
    logs = ""
    while time.time() < deadline:
        logs = run(["docker", "logs", container], capture=True, check=False)
        if needle in logs:
            return logs
        time.sleep(1)
    raise AssertionError(f"{container} logs did not contain {needle!r}\n{logs}")


def wait_for_new_log(container: str, needle: str, previous: str, *, timeout: float = 45.0) -> str:
    deadline = time.time() + timeout
    logs = previous
    while time.time() < deadline:
        logs = run(["docker", "logs", container], capture=True, check=False)
        if needle in logs[len(previous):]:
            return logs
        time.sleep(1)
    raise AssertionError(f"{container} new logs did not contain {needle!r}\n{logs}")


def wait_for_gate(host: Host, *, active: bool, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if status(host).active == active:
            return
        time.sleep(1)
    state = "open" if active else "closed"
    raise AssertionError(f"{host.name} gate did not become {state}")


def assert_biometric_required_fails_closed(host: Host) -> None:
    adb(["shell", "pm", "clear", PKG])
    stop_gate(host)
    register_host(host, skip_biometric=False)
    assert_ui_contains("Gate: CLOSED")
    tap_text("Start (1h)")
    assert_ui_contains("ERROR: NoBiometric", "No biometric enrolled")
    wait_for_gate(host, active=False)
    print("\nbiometric preflight: paired-mode Start failed closed when no biometric was enrolled.")


def assert_cli_identity(container: str) -> str:
    result = run_completed(["docker", "exec", container, "aws", "sts", "get-caller-identity"])
    if result.returncode != 0:
        raise AssertionError(f"{container} aws sts get-caller-identity failed\n{result.stdout}")
    data = json.loads(result.stdout)
    arn = data.get("Arn", "")
    expected = "arn:aws:sts::000000000000:assumed-role/phone-aws-sandbox-role/local-e2e"
    if arn != expected:
        raise AssertionError(f"{container} returned unexpected identity {data}")
    return result.stdout


def assert_cli_refused(container: str) -> str:
    result = run_completed(["docker", "exec", container, "aws", "sts", "get-caller-identity"])
    if result.returncode == 0:
        raise AssertionError(f"{container} unexpectedly got an identity\n{result.stdout}")
    if "Error retrieving metadata" not in result.stdout and "CredentialRetrievalError" not in result.stdout:
        raise AssertionError(f"{container} failed for an unexpected reason\n{result.stdout}")
    return result.stdout


def remove_servers(*containers: str) -> None:
    names = [name for name in containers if name]
    if names:
        run(["docker", "rm", "-f", *names], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-android-build", action="store_true")
    parser.add_argument("--keep-containers", action="store_true")
    args = parser.parse_args()

    host_a = Host("server-a", secrets.token_hex(32))
    host_b = Host("server-b", secrets.token_hex(32))

    server_a = ""
    server_b = ""
    try:
        vendor_id = start_local_stack()
        for host in (host_a, host_b):
            stop_gate(host)

        wait_for_adb()
        wait_for_emulator_host_port(18000)
        if not args.skip_android_build:
            build_and_install_app()

        assert_biometric_required_fails_closed(host_a)

        adb(["shell", "pm", "clear", PKG])
        register_hosts(host_a, host_b)
        assert_ui_contains("Use server-a", "Selected: server-b")

        image = docker_image()
        server_a = start_server_container(image, vendor_id, host_a)
        server_b = start_server_container(image, vendor_id, host_b)

        tap_text("Use server-a")
        assert_ui_contains("Selected: server-a", "Use server-b")
        tap_text("Start (1h)")
        wait_for_gate(host_a, active=True)
        wait_for_gate(host_b, active=False)

        logs_a = wait_for_log(server_a, "STS ok: arn:aws:sts::000000000000:assumed-role/phone-aws-sandbox-role/local-e2e")
        logs_b = wait_for_log(server_b, "gate-closed")
        cli_a = assert_cli_identity(server_a)
        assert_cli_refused(server_b)
        print("\nphase 1: server-a open, server-b closed")
        print("\n".join(logs_a.splitlines()[-4:]))
        print("\n".join(logs_b.splitlines()[-4:]))
        print(cli_a.strip())

        before_a = run(["docker", "logs", server_a], capture=True, check=False)
        before_b = run(["docker", "logs", server_b], capture=True, check=False)
        tap_text("Stop")
        wait_for_gate(host_a, active=False)
        tap_text("Use server-b")
        assert_ui_contains("Selected: server-b", "Use server-a")
        tap_text("Start (1h)")
        wait_for_gate(host_b, active=True)
        wait_for_gate(host_a, active=False)

        logs_a = wait_for_new_log(server_a, "gate-closed", before_a)
        logs_b = wait_for_new_log(server_b, "STS ok: arn:aws:sts::000000000000:assumed-role/phone-aws-sandbox-role/local-e2e", before_b)
        assert_cli_refused(server_a)
        cli_b = assert_cli_identity(server_b)
        print("\nphase 2: server-a closed, server-b open")
        print("\n".join(logs_a.splitlines()[-4:]))
        print("\n".join(logs_b.splitlines()[-4:]))
        print(cli_b.strip())

        print("\nE2E PASS: emulator registered two hosts, toggled A then B, and Docker verified the active host gets a local STS identity while the inactive host is refused.")
    finally:
        if not args.keep_containers:
            remove_servers(server_a, server_b)
            stop_local_stack()
        else:
            print("\nKeeping containers for inspection:")
            print(f"  docker exec -it {server_a} sh")
            print(f"  docker exec -it {server_b} sh")
            print("Inside the open host container, run:")
            print("  aws sts get-caller-identity")


if __name__ == "__main__":
    main()
