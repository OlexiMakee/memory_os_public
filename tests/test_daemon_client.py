from io import BytesIO
from urllib.error import HTTPError

from memory_os.toolkit.daemon_client import DaemonClient


def test_daemon_client_preserves_http_error_payload(tmp_path, monkeypatch):
    def fail(req, timeout):
        raise HTTPError(
            req.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid space"}'),
        )

    monkeypatch.setattr("memory_os.toolkit.daemon_client.urllib.request.urlopen", fail)

    response = DaemonClient(tmp_path, port=22467).request(
        "/space",
        method="POST",
        body={"space": "../../tmp"},
    )

    assert response.ok is False
    assert response.status_code == 400
    assert response.payload == {"error": "invalid space"}
    assert response.transport == "tcp"


def test_daemon_client_prefers_unix_socket(tmp_path, monkeypatch):
    socket_path = tmp_path / "data" / "memory_os.sock"
    socket_path.parent.mkdir(parents=True)
    socket_path.touch()
    sent = []

    class FakeSocket:
        chunks = [
            b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"status":"space_switched"}',
            b"",
        ]

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, path):
            assert path == str(socket_path)

        def sendall(self, data):
            sent.append(data)

        def recv(self, size):
            return self.chunks.pop(0)

        def close(self):
            return None

    monkeypatch.setattr("memory_os.toolkit.daemon_client.socket.socket", lambda *args: FakeSocket())

    response = DaemonClient(tmp_path, port=22467).request("/space", method="POST", body={"space": "dev"})

    assert response.ok is True
    assert response.transport == "unix"
    assert response.payload["status"] == "space_switched"
    assert b'POST /space HTTP/1.1' in sent[0]
    assert sent[0].endswith(b'{"space": "dev"}')
