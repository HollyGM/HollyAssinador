from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from datetime import datetime

from pyhanko import stamp
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.text import TextBoxStyle
from pyhanko.sign import fields, signers, timestamps
from pyhanko.sign.fields import SigSeedSubFilter


@dataclass(frozen=True)
class SignatureOptions:
    reason: str = ""
    location: str = ""
    tsa_url: str = ""
    appearance: str = "invisible"  # "invisible" ou "footer" (carimbo no rodapé)


class SigningError(RuntimeError):
    pass


@dataclass(frozen=True)
class SigningResult:
    path: Path
    notes: tuple[str, ...] = ()


HYBRID_NOTE = (
    "Este PDF usa referências cruzadas híbridas (estrutura incomum de alguns "
    "geradores de PDF). A assinatura foi feita em modo tolerante; alguns "
    "validadores estritos podem recusar a validação."
)


NO_SPACE_NOTE = (
    "Não havia área livre no rodapé da última página para o carimbo, então a "
    "assinatura foi feita sem aparência visual. Ela continua válida e aparece no "
    "painel de assinaturas do leitor de PDF."
)

STAMP_WIDTH = 300
STAMP_HEIGHT = 36


def _open_writer(inf) -> tuple[IncrementalPdfFileWriter, bool]:
    """Abre o PDF para assinatura incremental.

    Por segurança, o pyHanko recusa no modo estrito PDFs de referências híbridas
    (tabela xref clássica + /XRefStm). Só nesse caso reabre em modo tolerante, e
    devolve True para que o usuário seja avisado.
    """
    writer = IncrementalPdfFileWriter(inf)
    if not writer.prev.xrefs.hybrid_xrefs_present:
        return writer, False
    inf.seek(0)
    return IncrementalPdfFileWriter(inf, strict=False), True


def _field_name() -> str:
    return "Assinatura_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _metadata(field_name: str, opts: SignatureOptions) -> signers.PdfSignatureMetadata:
    return signers.PdfSignatureMetadata(
        field_name=field_name,
        md_algorithm="sha256",
        subfilter=SigSeedSubFilter.PADES,
        reason=opts.reason or None,
        location=opts.location or None,
    )


def _timestamper(opts: SignatureOptions):
    if not opts.tsa_url.strip():
        return None
    return timestamps.HTTPTimeStamper(url=opts.tsa_url.strip())


def _stamp_style():
    return stamp.TextStampStyle(
        stamp_text=(
            "Assinado digitalmente por\n"
            "%(signer)s\n"
            "Data: %(ts)s"
        ),
        timestamp_format="%d/%m/%Y %H:%M:%S %z",
        border_width=1,
        text_box_style=TextBoxStyle(font_size=7, leading=9),
    )


def _footer_box(src: Path):
    """Área livre no rodapé da última página, ou None se não houver (ou se falhar)."""
    try:
        from placement import find_free_box

        return find_free_box(src, STAMP_WIDTH, STAMP_HEIGHT)
    except Exception:
        return None


def _field_spec(field_name: str, box):
    if box is None:
        return None
    # Coordenadas em pontos PDF, na última página.
    return fields.SigFieldSpec(sig_field_name=field_name, on_page=-1, box=box)


def _sign_with_signer(
    input_pdf: str | Path,
    output_pdf: str | Path,
    signer,
    opts: SignatureOptions,
) -> SigningResult:
    src = Path(input_pdf).expanduser().resolve()
    dst = Path(output_pdf).expanduser().resolve()

    if not src.exists():
        raise SigningError(f"PDF de entrada não encontrado: {src}")
    if src.suffix.lower() != ".pdf":
        raise SigningError("O arquivo de entrada deve ser PDF.")
    if src == dst:
        raise SigningError("Escolha um arquivo de saída diferente do PDF original.")

    dst.parent.mkdir(parents=True, exist_ok=True)

    field_name = _field_name()
    meta = _metadata(field_name, opts)
    tsa = _timestamper(opts)
    notes: tuple[str, ...] = ()

    box = _footer_box(src) if opts.appearance == "footer" else None
    if opts.appearance == "footer" and box is None:
        notes += (NO_SPACE_NOTE,)

    try:
        with src.open("rb") as inf:
            writer, hybrid = _open_writer(inf)
            if hybrid:
                notes += (HYBRID_NOTE,)
            pdf_signer = signers.PdfSigner(
                signature_meta=meta,
                signer=signer,
                timestamper=tsa,
                stamp_style=_stamp_style() if box else None,
                new_field_spec=_field_spec(field_name, box),
            )
            with dst.open("wb") as outf:
                pdf_signer.sign_pdf(writer, output=outf)
    except Exception as exc:
        try:
            if dst.exists() and dst.stat().st_size == 0:
                dst.unlink()
        except OSError:
            pass
        raise SigningError(str(exc)) from exc

    if not dst.exists() or dst.stat().st_size == 0:
        raise SigningError("A biblioteca não produziu um PDF assinado.")

    return SigningResult(dst, notes)


def sign_pdf_a1(
    input_pdf: str | Path,
    output_pdf: str | Path,
    pkcs12_file: str | Path,
    password: str,
    opts: SignatureOptions,
) -> SigningResult:
    cert = Path(pkcs12_file).expanduser().resolve()
    if not cert.exists():
        raise SigningError(f"Certificado A1 não encontrado: {cert}")
    if cert.suffix.lower() not in {".p12", ".pfx"}:
        raise SigningError("Selecione um certificado .p12 ou .pfx.")

    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file=str(cert),
            passphrase=password.encode("utf-8") if password else None,
        )
    except Exception as exc:
        raise SigningError(
            "Não foi possível abrir o certificado A1. Confira o arquivo e a senha."
        ) from exc

    if signer is None:
        raise SigningError(
            "Não foi possível abrir o certificado A1. Confira o arquivo e a senha."
        )

    return _sign_with_signer(input_pdf, output_pdf, signer, opts)


def _cert_id(session, cert_label: str) -> Optional[bytes]:
    """ID (CKA_ID) do certificado no token, ou None se não for localizável.

    Por convenção do PKCS#11, a chave privada correspondente tem o mesmo ID.
    """
    try:
        from pkcs11 import Attribute, ObjectClass

        found = list(session.get_objects({
            Attribute.CLASS: ObjectClass.CERTIFICATE,
            Attribute.LABEL: cert_label,
        }))
        if len(found) != 1:
            return None
        return bytes(found[0][Attribute.ID]) or None
    except Exception:
        return None


def sign_pdf_a3(
    input_pdf: str | Path,
    output_pdf: str | Path,
    module_path: str | Path,
    token_label: str,
    cert_label: str,
    key_label: str,
    pin: str,
    opts: SignatureOptions,
) -> SigningResult:
    """
    Assina usando um token/cartão A3 através do módulo PKCS#11 do fabricante.

    No macOS, o fabricante normalmente instala um arquivo .dylib contendo a
    implementação PKCS#11. O módulo, o rótulo do token e o rótulo do certificado
    variam conforme o dispositivo.
    """
    module = Path(module_path).expanduser().resolve()
    if not module.exists():
        raise SigningError(f"Módulo PKCS#11 não encontrado: {module}")

    if not cert_label.strip():
        raise SigningError("Informe o rótulo (label) do certificado no token.")

    try:
        from pyhanko.config.pkcs11 import TokenCriteria
        from pyhanko.sign.pkcs11 import open_pkcs11_session, PKCS11Signer

        criteria = (
            TokenCriteria(label=token_label.strip())
            if token_label.strip()
            else None
        )

        session = open_pkcs11_session(
            lib_location=str(module),
            token_criteria=criteria,
            user_pin=pin if pin else None,
        )
    except Exception as exc:
        raise SigningError(
            "Não foi possível abrir o token A3. Confira o driver/módulo PKCS#11, "
            "o token selecionado e o PIN."
        ) from exc

    try:
        # Sem key label, o pyHanko procuraria a chave com o label do certificado,
        # que em vários tokens é diferente. Pelo ID não depende disso.
        cert_id = None if key_label.strip() else _cert_id(session, cert_label.strip())
        signer = PKCS11Signer(
            pkcs11_session=session,
            cert_label=cert_label.strip(),
            key_label=key_label.strip() or None,
            cert_id=cert_id,
            key_id=cert_id,
        )
        return _sign_with_signer(input_pdf, output_pdf, signer, opts)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(
            "Falha ao assinar com o A3. Confira os labels do certificado/chave "
            "e a compatibilidade do módulo PKCS#11."
        ) from exc
    finally:
        try:
            session.close()
        except Exception:
            pass
