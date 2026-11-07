from datetime import datetime, timezone
import time

from gcp_broker.main import create_app, secret_hash


HOST = "a" * 64
HOST_SECRET = "b" * 64
CONTROLLER_SECRET = "c" * 64


class MemoryStore:
    def __init__(self):
        self.data = {
            "host_hash": secret_hash(HOST_SECRET),
            "controller_hash": secret_hash(CONTROLLER_SECRET),
            "expires_at": 0,
        }
        self.generation = 1

    def read(self, host):
        return (self.data.copy(), self.generation) if host == HOST else (None, None)

    def write(self, host, data, generation):
        assert host == HOST and generation == self.generation
        self.data = data
        self.generation += 1


def test_grant_is_host_specific_and_stops_refresh():
    store = MemoryStore()

    def mint(lifetime):
        assert 0 < lifetime <= 900
        return {"accessToken": "synthetic", "expireTime": datetime.fromtimestamp(time.time() + lifetime, timezone.utc).isoformat()}

    client = create_app(store, mint).test_client()
    grant = f"/hosts/{HOST}/grant"
    token = f"/hosts/{HOST}/token"
    control = {"Authorization": f"Bearer {CONTROLLER_SECRET}"}
    request = {"grant_type": "refresh_token", "refresh_token": HOST_SECRET}

    assert client.post(token, data=request).status_code == 403
    assert client.put(grant, json={"duration_minutes": 15}, headers={"Authorization": f"Bearer {HOST_SECRET}"}).status_code == 403
    assert client.put(grant, json={"duration_minutes": True}, headers=control).status_code == 400
    assert client.put(grant, json={"duration_minutes": 15}, headers=control).status_code == 200
    assert client.post(token, data={**request, "refresh_token": CONTROLLER_SECRET}).status_code == 403
    assert client.post(f"/hosts/{'d' * 64}/token", data=request).status_code == 403
    response = client.post(token, data=request)
    assert response.json["access_token"] == "synthetic"
    assert response.headers["Cache-Control"] == "no-store"
    assert client.delete(grant, headers=control).json["expires_at"] == 0
    assert client.post(token, data=request).status_code == 403


def test_expiry_and_concurrent_stop_fail_closed():
    store = MemoryStore()

    def mint(lifetime):
        store.write(HOST, {**store.data, "expires_at": 0}, store.generation)
        return {"accessToken": "synthetic", "expireTime": datetime.fromtimestamp(time.time() + lifetime, timezone.utc).isoformat()}

    client = create_app(store, mint).test_client()
    path = f"/hosts/{HOST}/token"
    request = {"grant_type": "refresh_token", "refresh_token": HOST_SECRET}
    store.data["expires_at"] = int(time.time()) - 1
    assert client.post(path, data=request).status_code == 403
    assert store.generation == 1
    store.data["expires_at"] = int(time.time()) + 600
    assert client.post(path, data=request).status_code == 403
    assert store.generation == 2
