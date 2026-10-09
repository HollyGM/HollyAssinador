"""Autoteste do pacote: confere que as dependências e o fluxo de assinatura funcionam.

Uso: HollyAssinador --self-test   (ou: python app.py --self-test)

Cria certificado e PDF temporários (nada do usuário é lido) e assina com o
carimbo no rodapé, o que exercita pyHanko, pdfium e o PKCS#11 empacotados.
"""
from __future__ import annotations

import datetime
import tempfile
from pathlib import Path


def _pdf_bytes() -> bytes:
    content = b"BT /F1 12 Tf 72 700 Td (HollyAssinador autoteste) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return bytes(out)


def _pkcs12_bytes(password: bytes):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Autoteste")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    data = pkcs12.serialize_key_and_certificates(
        b"autoteste", key, cert, None, serialization.BestAvailableEncryption(password)
    )
    return data, cert


def run() -> int:
    import tkinter

    import pkcs11  # noqa: F401  (módulo nativo usado pelo A3)
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.pkcs11 import PKCS11Signer  # noqa: F401
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    from signer_core import SignatureOptions, sign_pdf_a1

    print(f"tkinter {tkinter.TkVersion}: ok")
    print("pkcs11: ok")

    password = b"autoteste"
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "entrada.pdf").write_bytes(_pdf_bytes())
        data, cert = _pkcs12_bytes(password)
        (folder / "cert.p12").write_bytes(data)

        result = sign_pdf_a1(
            folder / "entrada.pdf",
            folder / "saida.pdf",
            folder / "cert.p12",
            password.decode(),
            SignatureOptions(appearance="footer"),
        )
        if result.notes:
            print("FALHA: o carimbo no rodapé não foi aplicado:", *result.notes, sep="\n  ")
            return 1
        with result.path.open("rb") as handle:
            signatures = PdfFileReader(handle).embedded_signatures
            if len(signatures) != 1:
                print("FALHA: esperava 1 assinatura, achei", len(signatures))
                return 1
            status = validate_pdf_signature(
                signatures[0],
                ValidationContext(trust_roots=[signatures[0].signer_cert]),
            )
        if not (status.intact and status.valid):
            print("FALHA: assinatura gerada não valida")
            return 1
    print("assinatura PAdES com carimbo no rodapé (pdfium + pyHanko): ok")
    print("AUTOTESTE OK")
    return 0
