"""Local CA and server certificate for the device app."""

import ssl
from pathlib import Path

from cryptography import x509

from justai.tls import LocalTls, valid_name


def test_ca_and_server_certificate_cover_added_names(tmp_path: Path) -> None:
    tls = LocalTls(tmp_path, ["justai.lan"])
    tls.ensure()
    ctx = tls.server_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert tls.add_name("192.168.0.102") is True
    assert tls.add_name("192.168.0.102") is False
    cert = x509.load_pem_x509_certificate(tls.files.cert.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    names = {str(v) for v in san.get_values_for_type(x509.DNSName)} | \
            {str(v) for v in san.get_values_for_type(x509.IPAddress)}
    assert {"localhost", "justai.lan", "192.168.0.102"} <= names
    ca = x509.load_pem_x509_certificate(tls.files.ca_cert.read_bytes())
    assert cert.issuer == ca.subject
    # A restart keeps the CA (devices trust it) and the added name.
    again = LocalTls(tmp_path, ["justai.lan"])
    again.ensure()
    assert "192.168.0.102" in again.names() and again.ca_fingerprint() == tls.ca_fingerprint()


def test_name_validation() -> None:
    assert valid_name("192.168.0.102") and valid_name("justai.local")
    assert not valid_name("") and not valid_name("evil host") and not valid_name("a" * 300)
