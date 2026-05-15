from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


HTTPS_CA_CERT_NAME = "strokegpt-lan-ca.crt"
HTTPS_CA_KEY_NAME = "strokegpt-lan-ca-key.pem"
HTTPS_CERT_NAME = "strokegpt-lan-cert.pem"
HTTPS_KEY_NAME = "strokegpt-lan-key.pem"
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class ServerTlsError(RuntimeError):
    """Raised when HTTPS startup is requested but cannot be configured."""


@dataclass(frozen=True)
class ServerTlsConfig:
    enabled: bool
    scheme: str
    ssl_context: object | None = None
    source: str = ""
    cert_path: Path | None = None
    key_path: Path | None = None
    trust_cert_path: Path | None = None


def _env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _env_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def resolve_server_tls(
    env: Mapping[str, str] | None,
    cert_dir: Path,
    bind_host: str,
) -> ServerTlsConfig:
    env = env or os.environ
    cert_value = (env.get("STROKEGPT_SSL_CERT") or "").strip()
    key_value = (env.get("STROKEGPT_SSL_KEY") or "").strip()

    if cert_value or key_value:
        if not cert_value or not key_value:
            raise ServerTlsError("STROKEGPT_SSL_CERT and STROKEGPT_SSL_KEY must be set together.")
        cert_path = _env_path(cert_value)
        key_path = _env_path(key_value)
        if not cert_path.is_file():
            raise ServerTlsError(f"HTTPS certificate file was not found: {cert_path}")
        if not key_path.is_file():
            raise ServerTlsError(f"HTTPS private key file was not found: {key_path}")
        return ServerTlsConfig(
            enabled=True,
            scheme="https",
            ssl_context=(str(cert_path), str(key_path)),
            source="custom certificate",
            cert_path=cert_path,
            key_path=key_path,
        )

    https_value = env.get("STROKEGPT_HTTPS")
    if not _env_truthy(https_value):
        return ServerTlsConfig(enabled=False, scheme="http")

    if (https_value or "").strip().lower() in {"adhoc", "temporary"}:
        _require_cryptography("STROKEGPT_HTTPS=adhoc")
        return ServerTlsConfig(
            enabled=True,
            scheme="https",
            ssl_context="adhoc",
            source="temporary Werkzeug certificate",
        )

    cert_path, key_path, trust_cert_path = ensure_local_https_certificate(cert_dir, bind_host)
    return ServerTlsConfig(
        enabled=True,
        scheme="https",
        ssl_context=(str(cert_path), str(key_path)),
        source="generated local certificate",
        cert_path=cert_path,
        key_path=key_path,
        trust_cert_path=trust_cert_path,
    )


def ensure_local_https_certificate(cert_dir: Path, bind_host: str) -> tuple[Path, Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path = cert_dir / HTTPS_CA_CERT_NAME
    ca_key_path = cert_dir / HTTPS_CA_KEY_NAME
    cert_path = cert_dir / HTTPS_CERT_NAME
    key_path = cert_dir / HTTPS_KEY_NAME

    ca_cert, ca_key = _ensure_local_ca(ca_cert_path, ca_key_path)
    dns_names, ip_addresses = local_certificate_identities(bind_host)
    _write_server_certificate(cert_path, key_path, dns_names, ip_addresses, ca_cert, ca_key)
    return cert_path, key_path, ca_cert_path


def local_certificate_identities(bind_host: str) -> tuple[set[str], set[IpAddress]]:
    dns_names: set[str] = {"localhost"}
    ip_addresses: set[IpAddress] = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }

    def add_candidate(candidate: str | None) -> None:
        value = (candidate or "").strip().strip("[]")
        if not value or value in {"0.0.0.0", "::"}:
            return
        try:
            ip_addresses.add(ipaddress.ip_address(value))
        except ValueError:
            dns_names.add(value.lower())

    add_candidate(bind_host)
    for name in {socket.gethostname(), socket.getfqdn()}:
        add_candidate(name)
        try:
            for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(name, None):
                if family in {socket.AF_INET, socket.AF_INET6} and sockaddr:
                    add_candidate(str(sockaddr[0]))
        except OSError:
            continue

    return dns_names, ip_addresses


def _require_cryptography(reason: str):
    try:
        from cryptography import x509  # noqa: F401
    except ImportError as exc:
        raise ServerTlsError(
            f"{reason} requires the 'cryptography' package. Run "
            "'python -m pip install -r requirements.txt' and restart StrokeGPT."
        ) from exc


def _ensure_local_ca(ca_cert_path: Path, ca_key_path: Path):
    _require_cryptography("STROKEGPT_HTTPS=1")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    if ca_cert_path.is_file() and ca_key_path.is_file():
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        return ca_cert, ca_key

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.utcnow()
    ca_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StrokeGPT-ReVibed Local"),
            x509.NameAttribute(NameOID.COMMON_NAME, "StrokeGPT-ReVibed Local CA"),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_key_path.write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    try:
        ca_key_path.chmod(0o600)
    except OSError:
        pass
    return ca_cert, ca_key


def _write_server_certificate(
    cert_path: Path,
    key_path: Path,
    dns_names: set[str],
    ip_addresses: set[IpAddress],
    ca_cert,
    ca_key,
) -> None:
    _require_cryptography("STROKEGPT_HTTPS=1")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.datetime.utcnow()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StrokeGPT-ReVibed Local"),
            x509.NameAttribute(NameOID.COMMON_NAME, "StrokeGPT-ReVibed LAN"),
        ]
    )
    san_values = [x509.DNSName(name) for name in sorted(dns_names)]
    san_values.extend(x509.IPAddress(address) for address in sorted(ip_addresses, key=str))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
