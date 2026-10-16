"""Local HTTPS for the device app.

Browsers only allow microphone and camera access (and app installation) on secure
origins. JuStAI5 therefore runs its own small certificate authority:

* the CA is created once in ``<data>/tls`` (10 years) and can be installed on phones,
  tablets and PCs (``/api/tls/ca.crt``) - then the HTTPS port works without warnings;
* the server certificate lists all names/addresses JuStAI5 is reached under. An admin
  adds the address they use in the UI; the certificate is re-issued and loaded into
  the running HTTPS server without restart.

Server certificates are valid 825 days (Apple's limit for certificates of
user-installed CAs) and carry serverAuth EKU and subjectAltNames.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from justai.logging import get_logger

log = get_logger(__name__)

DEFAULT_NAMES = ("localhost", "127.0.0.1", "justai.local")
SERVER_DAYS = 825


@dataclass
class TlsFiles:
    directory: Path

    @property
    def ca_cert(self) -> Path:
        return self.directory / "ca.crt"

    @property
    def ca_key(self) -> Path:
        return self.directory / "ca.key"

    @property
    def cert(self) -> Path:
        return self.directory / "server.crt"

    @property
    def key(self) -> Path:
        return self.directory / "server.key"

    @property
    def names_file(self) -> Path:
        return self.directory / "names.json"


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def valid_name(name: str) -> bool:
    name = name.strip().lower()
    if not name or len(name) > 253:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return all(part and len(part) <= 63 and part.replace("-", "").isalnum() for part in name.split("."))


class LocalTls:
    def __init__(self, data_dir: Path, extra_names: list[str] | None = None) -> None:
        self.files = TlsFiles(data_dir / "tls")
        self.extra_names = [n for n in (extra_names or []) if valid_name(n)]
        self.contexts: list[ssl.SSLContext] = []  # live server contexts to reload

    # ------------------------------------------------------------------ names
    def names(self) -> list[str]:
        stored: list[str] = []
        if self.files.names_file.exists():
            stored = json.loads(self.files.names_file.read_text())
        return list(dict.fromkeys([*DEFAULT_NAMES, *self.extra_names, *stored]))

    def add_name(self, name: str) -> bool:
        """Add an address to the certificate; returns True if it was new."""
        name = name.strip().lower()
        if not valid_name(name):
            raise ValueError(f"invalid host name or address: {name}")
        names = self.names()
        if name in names:
            return False
        stored = [n for n in names if n not in DEFAULT_NAMES and n not in self.extra_names] + [name]
        self.files.names_file.write_text(json.dumps(stored))
        self._issue_server_cert()
        self.reload()
        return True

    # ------------------------------------------------------------ certificates
    def ensure(self) -> None:
        self.files.directory.mkdir(parents=True, exist_ok=True)
        if not self.files.ca_cert.exists() or not self.files.ca_key.exists():
            self._create_ca()
        if not self.files.cert.exists() or self._cert_names() != set(self.names()) or self._expires_soon():
            self._issue_server_cert()

    def _create_ca(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JuStAI5 lokale Zertifizierungsstelle"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JuStAI5")])
        now = dt.datetime.now(dt.UTC)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                             content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False,
                                             encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        _write_key(self.files.ca_key, key)
        self.files.ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        log.info("local certificate authority created")

    def _issue_server_cert(self) -> None:
        ca_key = serialization.load_pem_private_key(self.files.ca_key.read_bytes(), None)
        ca_cert = x509.load_pem_x509_certificate(self.files.ca_cert.read_bytes())
        assert isinstance(ca_key, ec.EllipticCurvePrivateKey)
        key = ec.generate_private_key(ec.SECP256R1())
        names = self.names()
        now = dt.datetime.now(dt.UTC)
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
                .issuer_name(ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=SERVER_DAYS))
                .add_extension(x509.SubjectAlternativeName([_san(n) for n in names]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                               critical=False)
                .sign(ca_key, hashes.SHA256()))
        _write_key(self.files.key, key)
        self.files.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM)
                                    + ca_cert.public_bytes(serialization.Encoding.PEM))
        log.info("https certificate issued", names=names)

    def _server_cert(self) -> x509.Certificate:
        return x509.load_pem_x509_certificate(self.files.cert.read_bytes())

    def _cert_names(self) -> set[str]:
        try:
            san = self._server_cert().extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except Exception:
            return set()
        return {str(v) for v in san.get_values_for_type(x509.DNSName)} | \
            {str(v) for v in san.get_values_for_type(x509.IPAddress)}

    def _expires_soon(self) -> bool:
        return self._server_cert().not_valid_after_utc - dt.datetime.now(dt.UTC) < dt.timedelta(days=30)

    def ca_fingerprint(self) -> str:
        cert = x509.load_pem_x509_certificate(self.files.ca_cert.read_bytes())
        return cert.fingerprint(hashes.SHA256()).hex(":").upper()

    # ---------------------------------------------------------------- servers
    def server_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.files.cert, self.files.key)
        self.contexts.append(ctx)
        return ctx

    def reload(self) -> None:
        """New handshakes use the re-issued certificate (no restart needed)."""
        for ctx in self.contexts:
            ctx.load_cert_chain(self.files.cert, self.files.key)
