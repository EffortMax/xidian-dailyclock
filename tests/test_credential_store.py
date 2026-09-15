import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.credential_store import CredentialStore, CredentialStoreError


class CredentialStoreTests(unittest.TestCase):
    def test_round_trip_uses_encrypted_password_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            store = CredentialStore(path)
            with patch.object(CredentialStore, "_protect", return_value=b"ciphertext"):
                store.save("  24000000000  ", "not-a-plaintext-password")

            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            self.assertEqual(payload["user_id"], "24000000000")
            self.assertIn("password_dpapi", payload)
            self.assertNotIn("not-a-plaintext-password", raw)

            with patch.object(CredentialStore, "_unprotect", return_value=b"not-a-plaintext-password"):
                saved = store.load()
            self.assertEqual(saved.user_id, "24000000000")
            self.assertEqual(saved.password, "not-a-plaintext-password")

    def test_invalid_file_is_reported_without_returning_partial_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text('{"version": 1, "user_id": "x"}', encoding="utf-8")
            with self.assertRaises(CredentialStoreError):
                CredentialStore(path).load()

    def test_clear_removes_credentials_and_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text("saved", encoding="utf-8")
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text("temporary", encoding="utf-8")
            CredentialStore(path).clear()
            self.assertFalse(path.exists())
            self.assertFalse(temporary.exists())


if __name__ == "__main__":
    unittest.main()
