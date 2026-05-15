import tempfile
import ipaddress
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
                config = resolve_server_tls(
                    {
                        "STROKEGPT_HTTPS": "1",
                        "STROKEGPT_HTTPS_IPS": "192.168.0.12,10.0.0.8",
                    },
                    Path(tmp),
                    "0.0.0.0",
                )

        ensure_cert.assert_called_once_with(
            Path(tmp),
            "0.0.0.0",
            extra_candidates=["192.168.0.12", "10.0.0.8"],
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.scheme, "https")
        self.assertEqual(config.ssl_context, (str(cert_path), str(key_path)))
        self.assertEqual(config.source, "generated local certificate")
        self.assertEqual(config.trust_cert_path, ca_path)

    def test_generated_https_certificate_chain_is_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path, key_path, ca_path = ensure_local_https_certificate(
                Path(tmp),
                "127.0.0.1",
                extra_candidates=["192.168.0.12"],
            )

            self.assertTrue(cert_path.is_file())
            self.assertTrue(key_path.is_file())
            self.assertTrue(ca_path.is_file())
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert_path), str(key_path))
            from cryptography import x509
            from cryptography.x509.oid import ExtensionOID

            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            not_valid_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after
            not_valid_before = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before
            valid_days = (not_valid_after - not_valid_before).days
            san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
            self.assertLessEqual(valid_days, 398)
            self.assertIn(ipaddress.ip_address("192.168.0.12"), san.get_values_for_type(x509.IPAddress))

    def test_adhoc_https_mode_uses_werkzeug_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("strokegpt.server_tls._require_cryptography") as require_crypto:
                config = resolve_server_tls({"STROKEGPT_HTTPS": "adhoc"}, Path(tmp), "127.0.0.1")

        require_crypto.assert_called_once_with("STROKEGPT_HTTPS=adhoc")
        self.assertTrue(config.enabled)
        self.assertEqual(config.ssl_context, "adhoc")

    def test_local_certificate_identities_include_loopback_and_bind_host(self):
        with mock.patch(
            "strokegpt.server_tls.local_route_addresses",
            return_value={ipaddress.ip_address("192.168.0.44")},
        ):
            dns_names, ip_addresses = local_certificate_identities("192.168.0.12")

        self.assertIn("localhost", dns_names)
        self.assertIn("127.0.0.1", {str(address) for address in ip_addresses})
        self.assertIn("192.168.0.12", {str(address) for address in ip_addresses})
        self.assertIn("192.168.0.44", {str(address) for address in ip_addresses})


if __name__ == "__main__":
    unittest.main()
