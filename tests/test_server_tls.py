import tempfile
import ssl
import unittest
from pathlib import Path
from unittest import mock

from strokegpt.server_tls import (
    ServerTlsError,
    ensure_local_https_certificate,
    local_certificate_identities,
    resolve_server_tls,
)


class ServerTlsTests(unittest.TestCase):
    def test_https_is_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = resolve_server_tls({}, Path(tmp), "127.0.0.1")

        self.assertFalse(config.enabled)
        self.assertEqual(config.scheme, "http")
        self.assertIsNone(config.ssl_context)

    def test_custom_certificate_and_key_enable_https(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            cert_path.write_text("cert", encoding="utf-8")
            key_path.write_text("key", encoding="utf-8")

            config = resolve_server_tls(
                {
                    "STROKEGPT_SSL_CERT": str(cert_path),
                    "STROKEGPT_SSL_KEY": str(key_path),
                },
                Path(tmp) / "generated",
                "0.0.0.0",
            )

        self.assertTrue(config.enabled)
        self.assertEqual(config.scheme, "https")
        self.assertEqual(config.ssl_context, (str(cert_path), str(key_path)))
        self.assertEqual(config.source, "custom certificate")

    def test_custom_certificate_requires_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ServerTlsError, "must be set together"):
                resolve_server_tls({"STROKEGPT_SSL_CERT": "cert.pem"}, Path(tmp), "0.0.0.0")

    def test_generated_https_uses_persistent_cert_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            ca_path = Path(tmp) / "ca.crt"
            with mock.patch(
                "strokegpt.server_tls.ensure_local_https_certificate",
                return_value=(cert_path, key_path, ca_path),
            ) as ensure_cert:
                config = resolve_server_tls({"STROKEGPT_HTTPS": "1"}, Path(tmp), "0.0.0.0")

        ensure_cert.assert_called_once()
        self.assertTrue(config.enabled)
        self.assertEqual(config.scheme, "https")
        self.assertEqual(config.ssl_context, (str(cert_path), str(key_path)))
        self.assertEqual(config.source, "generated local certificate")
        self.assertEqual(config.trust_cert_path, ca_path)

    def test_generated_https_certificate_chain_is_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path, key_path, ca_path = ensure_local_https_certificate(Path(tmp), "127.0.0.1")

            self.assertTrue(cert_path.is_file())
            self.assertTrue(key_path.is_file())
            self.assertTrue(ca_path.is_file())
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert_path), str(key_path))

    def test_adhoc_https_mode_uses_werkzeug_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("strokegpt.server_tls._require_cryptography") as require_crypto:
                config = resolve_server_tls({"STROKEGPT_HTTPS": "adhoc"}, Path(tmp), "127.0.0.1")

        require_crypto.assert_called_once_with("STROKEGPT_HTTPS=adhoc")
        self.assertTrue(config.enabled)
        self.assertEqual(config.ssl_context, "adhoc")

    def test_local_certificate_identities_include_loopback_and_bind_host(self):
        dns_names, ip_addresses = local_certificate_identities("192.168.0.12")

        self.assertIn("localhost", dns_names)
        self.assertIn("127.0.0.1", {str(address) for address in ip_addresses})
        self.assertIn("192.168.0.12", {str(address) for address in ip_addresses})


if __name__ == "__main__":
    unittest.main()
