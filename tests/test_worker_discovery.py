import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.python import worker_client


class WorkerDiscoveryTests(unittest.TestCase):
    def test_enrollment_saves_server_scoped_worker_token(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": temp, "APPDATA": temp}):
                response = Mock()
                response.status_code = 201
                response.json.return_value = {
                    "worker_id": 42,
                    "name": "render-node",
                    "worker_token": "worker-secret",
                }
                with patch.object(worker_client.requests, "post", return_value=response) as post:
                    token = worker_client.enroll_worker("https://blendswarm.com", "temporary-code")

                self.assertEqual(token, "worker-secret")
                post.assert_called_once()
                payload = post.call_args.kwargs["json"]
                self.assertEqual(payload["code"], "temporary-code")
                self.assertGreaterEqual(payload["cpu_cores"], 1)
                self.assertGreaterEqual(payload["memory_gb"], 1)
                self.assertGreaterEqual(payload["storage_gb"], 1)

                token_path = worker_client._worker_token_path("https://blendswarm.com")
                saved = json.loads(token_path.read_text(encoding="utf-8"))
                self.assertEqual(saved, {
                    "server": "https://blendswarm.com",
                    "token": "worker-secret",
                })
                if os.name != "nt":
                    self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_enrollment_surfaces_server_rejection(self):
        response = Mock()
        response.status_code = 400
        response.json.return_value = {"detail": "Discovery code expired"}
        with patch.object(worker_client.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Discovery code expired"):
                worker_client.enroll_worker("https://blendswarm.com", "expired-code")


if __name__ == "__main__":
    unittest.main()
