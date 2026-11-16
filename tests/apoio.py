"""Apoio dos testes: PDFs e certificados A1 fictícios, criados em pastas temporárias."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from selftest import _pdf_bytes  # noqa: E402

SENHA = "teste"
TSA_FORA_DO_AR = "http://127.0.0.1:9/"  # porta "discard": a conexão é recusada na hora

_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def certificado(
    nome: str = "Teste",
    inicio: datetime.timedelta = datetime.timedelta(minutes=-1),
    fim: datetime.timedelta = datetime.timedelta(days=365),
) -> x509.Certificate:
    """Certificado autoassinado; inicio/fim são deslocamentos a partir de agora."""
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    momento = agora()
    return (
        x509.CertificateBuilder()
        .subject_name(sujeito)
        .issuer_name(sujeito)
        .public_key(_CHAVE.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(momento + inicio)
        .not_valid_after(momento + fim)
        .sign(_CHAVE, hashes.SHA256())
    )


def a1(pasta: Path, nome_arquivo: str = "cert.p12", **kwargs) -> Path:
    """Grava um .p12 com senha SENHA e devolve o caminho."""
    cert = certificado(**kwargs)
    dados = pkcs12.serialize_key_and_certificates(
        b"teste", _CHAVE, cert, None, serialization.BestAvailableEncryption(SENHA.encode())
    )
    caminho = pasta / nome_arquivo
    caminho.write_bytes(dados)
    return caminho


def asn1(cert: x509.Certificate):
    """O mesmo certificado no formato que o pyHanko entrega (asn1crypto)."""
    from asn1crypto import x509 as ax

    return ax.Certificate.load(cert.public_bytes(serialization.Encoding.DER))


def pdf(caminho: Path, conteudo: bytes | None = None) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo if conteudo is not None else _pdf_bytes())
    return caminho


def assinaturas(caminho: Path):
    from pyhanko.pdf_utils.reader import PdfFileReader

    with caminho.open("rb") as fh:
        return list(PdfFileReader(fh).embedded_signatures)


def assinatura_valida(caminho: Path) -> bool:
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    with caminho.open("rb") as fh:
        sigs = PdfFileReader(fh).embedded_signatures
        if len(sigs) != 1:
            return False
        status = validate_pdf_signature(
            sigs[0], ValidationContext(trust_roots=[sigs[0].signer_cert])
        )
        return bool(status.intact and status.valid)


def texto_dos_carimbos(caminho: Path) -> bytes:
    """Conteúdo bruto das aparências dos campos de assinatura (onde fica o texto do carimbo)."""
    from pyhanko.pdf_utils.reader import PdfFileReader

    blob = b""

    def coletar(obj):
        nonlocal blob
        obj = obj.get_object()
        blob += getattr(obj, "data", b"")
        for xo in obj.get("/Resources", {}).get("/XObject", {}).values():
            coletar(xo)

    with caminho.open("rb") as fh:
        leitor = PdfFileReader(fh)
        for campo in leitor.root["/AcroForm"]["/Fields"]:
            campo = campo.get_object()
            for widget in campo.get("/Kids", [campo]):
                ap = widget.get_object().get("/AP")
                if ap is not None:
                    coletar(ap["/N"])
    return blob


def disco_diferencia_maiusculas(pasta: Path) -> bool:
    teste = pasta / "Maiuscula.tmp"
    teste.write_bytes(b"")
    try:
        return not (pasta / "maiuscula.tmp").exists()
    finally:
        teste.unlink()
