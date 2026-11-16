from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


@dataclass(frozen=True)
class BatchOutcome:
    """Resultado de um PDF dentro de uma assinatura em lote."""

    src: Path
    dst: Path
    result: Optional[SigningResult] = None
    error: Optional[str] = None


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

# Avisa quando faltar menos que isto para o certificado vencer.
EXPIRY_WARNING_DAYS = 30

# No padrão ICP-Brasil o nome comum do certificado é "NOME:CPF" (e-CPF) ou
# "RAZÃO SOCIAL:CNPJ" (e-CNPJ). O número não deve ir para o carimbo visível.
_ICP_DOCUMENT_SUFFIX = re.compile(r"\s*:\s*\d{11}(?:\d{3})?\s*$")


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


def _date(moment: datetime) -> str:
    return moment.astimezone().strftime("%d/%m/%Y")


def certificate_notes(cert, now: Optional[datetime] = None) -> tuple[str, ...]:
    """Recusa certificado vencido (ou ainda não válido) e avisa quando está perto de vencer."""
    if cert is None:
        return ()
    now = now or datetime.now(timezone.utc)
    start, end = cert.not_valid_before, cert.not_valid_after
    if now > end:
        raise SigningError(
            f"O certificado venceu em {_date(end)}. Uma assinatura feita com ele "
            "seria recusada pelos validadores. Renove o certificado antes de assinar."
        )
    if now < start:
        raise SigningError(
            f"O certificado só passa a valer em {_date(start)}. "
            "Confira a data e a hora do Mac."
        )
    # Dias de calendário no fuso do Mac, para "hoje" e "amanhã" baterem com a data mostrada.
    days = (end.astimezone().date() - now.astimezone().date()).days
    if days >= EXPIRY_WARNING_DAYS:
        return ()
    if days == 0:
        when = f"vence hoje ({_date(end)})"
    elif days == 1:
        when = f"vence amanhã ({_date(end)})"
    else:
        when = f"vence em {_date(end)}, daqui a {days} dias"
    return (f"O certificado {when}. Providencie a renovação.",)


def display_name(cert) -> Optional[str]:
    """Nome para o carimbo visível, sem o CPF/CNPJ que o padrão ICP-Brasil põe no nome."""
    if cert is None:
        return None
    subject = cert.subject.native
    name = subject.get("common_name") or subject.get("organization_name")
    if isinstance(name, (list, tuple)):
        name = name[0] if name else None
    if not name:
        return None
    return _ICP_DOCUMENT_SUFFIX.sub("", str(name)).strip() or None


def friendly_error(exc: BaseException) -> str:
    """Traduz os erros mais comuns das bibliotecas para uma mensagem em português."""
    import pkcs11.exceptions as p11
    from pyhanko.pdf_utils.crypt.api import PdfKeyNotAvailableError
    from pyhanko.pdf_utils.misc import PdfReadError
    from pyhanko.sign.timestamps.common_utils import TimestampRequestError

    if isinstance(exc, TimestampRequestError):
        return (
            "Não foi possível obter o carimbo do tempo na TSA informada (endereço "
            "fora do ar, errado ou sem internet). Nada foi gravado. Confira a URL da "
            "TSA ou deixe o campo vazio para assinar sem ela."
        )
    if isinstance(exc, PdfKeyNotAvailableError):
        return (
            "Este PDF está protegido por senha. Remova a proteção (ou gere o PDF de "
            "novo, sem senha) antes de assinar."
        )
    if isinstance(exc, PdfReadError):
        return (
            "Não foi possível ler o PDF. O arquivo pode estar corrompido ou não ser "
            "um PDF de verdade."
        )
    if isinstance(exc, (p11.DeviceRemoved, p11.TokenNotPresent)):
        return (
            "O token foi desconectado durante a assinatura. Nada foi gravado; "
            "conecte-o e tente de novo."
        )
    if isinstance(exc, PermissionError):
        return (
            "Sem permissão para ler ou gravar o arquivo. Confira se a pasta permite "
            "gravação e se o macOS deu ao HollyAssinador acesso a ela."
        )
    return f"Falha na assinatura: {exc}"


def same_file(a: Path, b: Path) -> bool:
    """True se os dois caminhos levam ao mesmo arquivo.

    O disco do Mac normalmente não diferencia maiúsculas de minúsculas, então
    "Contrato.pdf" e "contrato.pdf" são o mesmo arquivo, embora os nomes difiram.
    """
    if a == b:
        return True
    try:
        return b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def sign_file(
    signer,
    input_pdf: str | Path,
    output_pdf: str | Path,
    opts: SignatureOptions,
) -> SigningResult:
    """Assina um PDF com um signer já aberto (A1 ou A3).

    O PDF assinado é gravado primeiro num arquivo temporário na pasta de destino
    e só no fim substitui o destino. Se algo falhar no meio, um arquivo que já
    existisse com o nome de saída fica intacto.
    """
    src = Path(input_pdf).expanduser().resolve()
    dst = Path(output_pdf).expanduser().resolve()

    if not src.exists():
        raise SigningError(f"PDF de entrada não encontrado: {src}")
    if src.suffix.lower() != ".pdf":
        raise SigningError("O arquivo de entrada deve ser PDF.")
    if same_file(src, dst):
        raise SigningError("Escolha um arquivo de saída diferente do PDF original.")

    notes: tuple[str, ...] = certificate_notes(signer.signing_cert)

    field_name = _field_name()
    meta = _metadata(field_name, opts)
    tsa = _timestamper(opts)

    box = _footer_box(src) if opts.appearance == "footer" else None
    if opts.appearance == "footer" and box is None:
        notes += (NO_SPACE_NOTE,)
    text_params = {}
    name = display_name(signer.signing_cert)
    if name:
        text_params["signer"] = name

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".HollyAssinador-", suffix=".pdf", dir=dst.parent
        )
    except OSError as exc:
        raise SigningError(
            f"Não foi possível gravar na pasta {dst.parent}: {exc.strerror or exc}"
        ) from exc
    tmp = Path(tmp_name)

    try:
        with os.fdopen(fd, "wb") as outf, src.open("rb") as inf:
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
            pdf_signer.sign_pdf(
                writer, output=outf, appearance_text_params=text_params or None
            )
        if tmp.stat().st_size == 0:
            raise SigningError("A biblioteca não produziu um PDF assinado.")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except SigningError:
        _discard(tmp)
        raise
    except Exception as exc:
        _discard(tmp)
        raise SigningError(friendly_error(exc)) from exc

    return SigningResult(dst, notes)


def output_for(src: str | Path, folder: str | Path | None = None) -> Path:
    """Nome padrão do PDF assinado: "<nome>-assinado.pdf", na pasta indicada ou na do original."""
    src = Path(src).expanduser().resolve()
    base = Path(folder).expanduser().resolve() if folder else src.parent
    return base / f"{src.stem}-assinado.pdf"


def plan_batch(
    inputs: Iterable[str | Path], folder: str | Path | None = None
) -> list[tuple[Path, Path]]:
    """Pares (original, assinado) de um lote, recusando nomes de saída que colidem."""
    sources = [Path(p).expanduser().resolve() for p in inputs]
    source_keys = {str(p).casefold() for p in sources}
    seen: set[str] = set()
    pairs = []
    for src in sources:
        dst = output_for(src, folder)
        key = str(dst).casefold()
        if key in seen:
            raise SigningError(
                f"Dois PDFs gerariam o mesmo arquivo assinado ({dst.name}). "
                "Assine-os separadamente ou escolha outra pasta de saída."
            )
        if key in source_keys:
            raise SigningError(
                f"O arquivo assinado de {src.name} substituiria outro PDF da lista "
                f"({dst.name}). Tire um dos dois da seleção."
            )
        seen.add(key)
        pairs.append((src, dst))
    return pairs


def sign_batch(
    signer,
    pairs: Iterable[tuple[str | Path, str | Path]],
    opts: SignatureOptions,
    progress: Optional[Callable[[int, int, Path], None]] = None,
) -> list[BatchOutcome]:
    """Assina vários PDFs com o mesmo signer (o PIN do A3 é pedido uma vez só).

    Um PDF com problema não interrompe os demais; o erro fica no resultado dele.
    Certificado vencido interrompe antes do primeiro arquivo.
    """
    pairs = [(Path(s), Path(d)) for s, d in pairs]
    certificate_notes(signer.signing_cert)
    outcomes = []
    for index, (src, dst) in enumerate(pairs, 1):
        if progress:
            progress(index, len(pairs), src)
        try:
            result = sign_file(signer, src, dst, opts)
            outcomes.append(BatchOutcome(src, dst, result=result))
        except SigningError as exc:
            outcomes.append(BatchOutcome(src, dst, error=str(exc)))
    return outcomes


def load_a1(pkcs12_file: str | Path, password: str):
    """Abre o certificado A1 (.p12/.pfx) e devolve o signer."""
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
    return signer


def sign_pdf_a1(
    input_pdf: str | Path,
    output_pdf: str | Path,
    pkcs12_file: str | Path,
    password: str,
    opts: SignatureOptions,
) -> SigningResult:
    return sign_file(load_a1(pkcs12_file, password), input_pdf, output_pdf, opts)


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


def token_open_error(exc: BaseException) -> str:
    """Mensagem para falha ao abrir o token, distinguindo PIN errado, bloqueado e token ausente."""
    import pkcs11.exceptions as p11

    if isinstance(exc, p11.PinIncorrect):
        return (
            "PIN incorreto. Atenção: o token bloqueia depois de algumas tentativas "
            "erradas. Confira o PIN com calma antes de tentar de novo."
        )
    if isinstance(exc, p11.PinLocked):
        return (
            "O PIN do token está bloqueado por excesso de tentativas erradas. "
            "Desbloqueie-o no programa do fabricante do token (por exemplo, o SafeNet "
            "Authentication Client), que pede a senha de administrador."
        )
    if isinstance(exc, p11.PinExpired):
        return "O PIN do token expirou. Troque-o no programa do fabricante do token."
    if isinstance(exc, (p11.PinLenRange, p11.PinInvalid)):
        return "O PIN digitado não tem o formato aceito pelo token. Confira e digite de novo."
    if isinstance(
        exc,
        (p11.TokenNotPresent, p11.NoSuchToken, p11.DeviceRemoved, p11.TokenNotRecognised),
    ) or "no token" in str(exc).lower():
        return (
            "Nenhum token encontrado. Confira se o token está conectado e se o "
            "campo \"Token label\" está correto."
        )
    return (
        "Não foi possível abrir o token A3. Confira o módulo PKCS#11 (driver do "
        "fabricante), o token selecionado e o PIN."
    )


@contextmanager
def open_a3(
    module_path: str | Path,
    token_label: str,
    cert_label: str,
    key_label: str,
    pin: str,
) -> Iterator:
    """Abre o token/cartão A3 uma vez e entrega o signer; fecha a sessão no fim.

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
        from pyhanko.sign.pkcs11 import PKCS11Signer, open_pkcs11_session

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
        raise SigningError(token_open_error(exc)) from exc

    try:
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
            signer.signing_cert  # carrega certificado e chave agora, para errar cedo
        except Exception as exc:
            if not pin:
                raise SigningError(
                    "Digite o PIN do token: sem ele o token não libera o certificado "
                    "e a chave."
                ) from exc
            raise SigningError(
                "Não foi possível localizar o certificado e a chave no token. Confira o "
                "\"Certificate label\" e, se preenchido, o \"Key label\"."
            ) from exc
        yield signer
    finally:
        try:
            session.close()
        except Exception:
            pass


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
    """Assina usando um token/cartão A3 através do módulo PKCS#11 do fabricante."""
    with open_a3(module_path, token_label, cert_label, key_label, pin) as signer:
        return sign_file(signer, input_pdf, output_pdf, opts)
