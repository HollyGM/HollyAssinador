"""Testes do núcleo de assinatura, com certificados e PDFs fictícios."""
from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path

from tests import apoio
from signer_core import (
    SignatureOptions,
    SigningError,
    certificate_notes,
    display_name,
    friendly_error,
    load_a1,
    open_a3,
    plan_batch,
    sign_batch,
    sign_pdf_a1,
    token_open_error,
)

DIA = datetime.timedelta(days=1)


class BaseTemporaria(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.cert = apoio.a1(self.pasta)

    def tearDown(self):
        self._tmp.cleanup()

    def assinar(self, src, dst, opts=None, cert=None):
        return sign_pdf_a1(src, dst, cert or self.cert, apoio.SENHA, opts or SignatureOptions())

    def temporarios_restantes(self):
        return list(self.pasta.glob(".HollyAssinador-*"))


class AssinaturaBasicaTests(BaseTemporaria):
    def test_assina_e_a_assinatura_valida(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        resultado = self.assinar(src, self.pasta / "peticao-assinado.pdf")
        self.assertEqual(resultado.notes, ())
        self.assertTrue(apoio.assinatura_valida(resultado.path))
        self.assertEqual(self.temporarios_restantes(), [])

    def test_original_nao_e_alterado(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        antes = src.read_bytes()
        self.assinar(src, self.pasta / "peticao-assinado.pdf")
        self.assertEqual(src.read_bytes(), antes)


class GravacaoSeguraTests(BaseTemporaria):
    """Item 1 da revisão: falhas não podem destruir arquivos."""

    def test_falha_preserva_assinado_que_ja_existia(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        dst = self.pasta / "peticao-assinado.pdf"
        dst.write_bytes(b"%PDF versao anterior, ja assinada e protocolada")
        antes = dst.read_bytes()
        with self.assertRaises(SigningError):
            self.assinar(src, dst, SignatureOptions(tsa_url=apoio.TSA_FORA_DO_AR))
        self.assertEqual(dst.read_bytes(), antes)
        self.assertEqual(self.temporarios_restantes(), [])

    def test_falha_sem_arquivo_anterior_nao_deixa_lixo(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        dst = self.pasta / "peticao-assinado.pdf"
        with self.assertRaises(SigningError):
            self.assinar(src, dst, SignatureOptions(tsa_url=apoio.TSA_FORA_DO_AR))
        self.assertFalse(dst.exists())
        self.assertEqual(self.temporarios_restantes(), [])

    def test_sucesso_substitui_arquivo_existente(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        dst = self.pasta / "peticao-assinado.pdf"
        dst.write_bytes(b"antigo")
        self.assinar(src, dst)
        self.assertTrue(apoio.assinatura_valida(dst))

    def test_saida_igual_ao_original_e_recusada(self):
        src = apoio.pdf(self.pasta / "Contrato.pdf")
        with self.assertRaises(SigningError):
            self.assinar(src, src)

    def test_saida_so_com_maiusculas_diferentes_nao_destroi_original(self):
        if apoio.disco_diferencia_maiusculas(self.pasta):
            self.skipTest("este disco diferencia maiúsculas de minúsculas")
        src = apoio.pdf(self.pasta / "Contrato.pdf")
        antes = src.read_bytes()
        with self.assertRaises(SigningError):
            self.assinar(src, self.pasta / "contrato.pdf")
        self.assertEqual(src.read_bytes(), antes)


class ValidadeDoCertificadoTests(BaseTemporaria):
    """Item 2 da revisão: certificado vencido não assina; perto de vencer, avisa."""

    def test_certificado_vencido_e_recusado(self):
        vencido = apoio.a1(self.pasta, "vencido.p12", inicio=-30 * DIA, fim=-DIA)
        src = apoio.pdf(self.pasta / "peticao.pdf")
        dst = self.pasta / "peticao-assinado.pdf"
        with self.assertRaisesRegex(SigningError, "venceu"):
            self.assinar(src, dst, cert=vencido)
        self.assertFalse(dst.exists())

    def test_certificado_ainda_nao_valido_e_recusado(self):
        futuro = apoio.a1(self.pasta, "futuro.p12", inicio=2 * DIA, fim=30 * DIA)
        src = apoio.pdf(self.pasta / "peticao.pdf")
        with self.assertRaisesRegex(SigningError, "só passa a valer"):
            self.assinar(src, self.pasta / "saida.pdf", cert=futuro)

    def test_aviso_quando_falta_pouco_para_vencer(self):
        quase = apoio.a1(self.pasta, "quase.p12", fim=10 * DIA)
        src = apoio.pdf(self.pasta / "peticao.pdf")
        resultado = self.assinar(src, self.pasta / "saida.pdf", cert=quase)
        self.assertEqual(len(resultado.notes), 1)
        self.assertIn("Providencie a renovação", resultado.notes[0])
        self.assertTrue(apoio.assinatura_valida(resultado.path))

    def test_textos_de_vence_hoje_e_amanha(self):
        cert = apoio.asn1(apoio.certificado(inicio=-10 * DIA, fim=datetime.timedelta(hours=3)))
        # início (00:00:01) do dia, no fuso do Mac, em que o certificado vence
        dia_do_vencimento = cert.not_valid_after.astimezone().replace(
            hour=0, minute=0, second=1, microsecond=0
        )
        self.assertIn("vence hoje", certificate_notes(cert, dia_do_vencimento)[0])
        self.assertIn("vence amanhã", certificate_notes(cert, dia_do_vencimento - DIA)[0])
        self.assertIn("daqui a 5 dias", certificate_notes(cert, dia_do_vencimento - 5 * DIA)[0])

    def test_sem_aviso_quando_longe_de_vencer(self):
        cert = apoio.asn1(apoio.certificado(fim=365 * DIA))
        self.assertEqual(certificate_notes(cert), ())

    def test_lote_com_certificado_vencido_nao_assina_nada(self):
        vencido = load_a1(apoio.a1(self.pasta, "vencido.p12", inicio=-30 * DIA, fim=-DIA), apoio.SENHA)
        pares = plan_batch([apoio.pdf(self.pasta / "a.pdf"), apoio.pdf(self.pasta / "b.pdf")])
        with self.assertRaisesRegex(SigningError, "venceu"):
            sign_batch(vencido, pares, SignatureOptions())
        self.assertFalse(any(dst.exists() for _, dst in pares))


class CarimboTests(BaseTemporaria):
    """Item 3 da revisão: o carimbo visível não mostra CPF/CNPJ."""

    def test_carimbo_mostra_nome_sem_cpf(self):
        icp = apoio.a1(self.pasta, "icp.p12", nome="FULANO DE TAL:12345678909")
        src = apoio.pdf(self.pasta / "peticao.pdf")
        resultado = self.assinar(
            src, self.pasta / "saida.pdf", SignatureOptions(appearance="footer"), cert=icp
        )
        self.assertEqual(resultado.notes, ())
        texto = apoio.texto_dos_carimbos(resultado.path)
        self.assertIn(b"FULANO DE TAL", texto)
        self.assertNotIn(b"12345678909", texto)
        self.assertTrue(apoio.assinatura_valida(resultado.path))

    def test_nome_para_exibicao(self):
        def nome(cn):
            return display_name(apoio.asn1(apoio.certificado(nome=cn)))

        self.assertEqual(nome("FULANO DE TAL:12345678909"), "FULANO DE TAL")
        self.assertEqual(nome("EMPRESA LTDA:12345678000199"), "EMPRESA LTDA")
        self.assertEqual(nome("Maria Souza"), "Maria Souza")
        self.assertEqual(nome("Escritório: filial Natal"), "Escritório: filial Natal")


class MensagensTests(BaseTemporaria):
    """Item 5 da revisão: erros comuns em português e PIN errado distinto de token ausente."""

    def test_tsa_fora_do_ar(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        with self.assertRaisesRegex(SigningError, "carimbo do tempo"):
            self.assinar(src, self.pasta / "s.pdf", SignatureOptions(tsa_url=apoio.TSA_FORA_DO_AR))

    def test_pdf_protegido_por_senha(self):
        import io

        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.pdf_utils.writer import copy_into_new_writer
        from selftest import _pdf_bytes

        writer = copy_into_new_writer(PdfFileReader(io.BytesIO(_pdf_bytes())))
        writer.encrypt("dono", "usuario")
        buf = io.BytesIO()
        writer.write(buf)
        src = apoio.pdf(self.pasta / "protegido.pdf", buf.getvalue())
        with self.assertRaisesRegex(SigningError, "protegido por senha"):
            self.assinar(src, self.pasta / "s.pdf")

    def test_arquivo_que_nao_e_pdf(self):
        src = apoio.pdf(self.pasta / "falso.pdf", b"isto nao e um pdf")
        with self.assertRaisesRegex(SigningError, "Não foi possível ler o PDF"):
            self.assinar(src, self.pasta / "s.pdf")

    def test_erros_do_token(self):
        import pkcs11
        import pkcs11.exceptions as p11

        self.assertIn("PIN incorreto", token_open_error(p11.PinIncorrect()))
        self.assertIn("bloqueado", token_open_error(p11.PinLocked()))
        self.assertIn("expirou", token_open_error(p11.PinExpired()))
        self.assertIn("Nenhum token", token_open_error(p11.NoSuchToken()))
        self.assertIn("Nenhum token", token_open_error(p11.TokenNotPresent()))
        self.assertIn("Nenhum token", token_open_error(pkcs11.PKCS11Error("No token found")))
        self.assertIn("Não foi possível abrir o token", token_open_error(RuntimeError("x")))

    def test_token_desconectado_durante_assinatura(self):
        import pkcs11.exceptions as p11

        self.assertIn("desconectado", friendly_error(p11.DeviceRemoved()))

    def test_modulo_inexistente(self):
        with self.assertRaisesRegex(SigningError, "Módulo PKCS#11 não encontrado"):
            with open_a3(self.pasta / "nao-existe.dylib", "", "cert", "", "1234"):
                pass


class LoteTests(BaseTemporaria):
    """Item 7 da revisão: assinatura em lote."""

    def test_nomes_padrao_ao_lado_dos_originais(self):
        a = apoio.pdf(self.pasta / "a.pdf")
        b = apoio.pdf(self.pasta / "sub" / "b.pdf")
        pares = plan_batch([a, b])
        self.assertEqual(pares[0][1], a.resolve().with_name("a-assinado.pdf"))
        self.assertEqual(pares[1][1], b.resolve().with_name("b-assinado.pdf"))

    def test_pasta_de_saida_escolhida(self):
        a = apoio.pdf(self.pasta / "a.pdf")
        destino = self.pasta / "assinados"
        self.assertEqual(plan_batch([a], destino)[0][1], destino.resolve() / "a-assinado.pdf")

    def test_mesmo_nome_de_saida_e_recusado(self):
        a1 = apoio.pdf(self.pasta / "x" / "procuracao.pdf")
        a2 = apoio.pdf(self.pasta / "y" / "procuracao.pdf")
        with self.assertRaisesRegex(SigningError, "mesmo arquivo assinado"):
            plan_batch([a1, a2], self.pasta / "assinados")

    def test_saida_que_substituiria_outro_pdf_da_lista_e_recusada(self):
        a = apoio.pdf(self.pasta / "a.pdf")
        b = apoio.pdf(self.pasta / "a-assinado.pdf")
        with self.assertRaisesRegex(SigningError, "substituiria outro PDF"):
            plan_batch([a, b])

    def test_lote_continua_quando_um_pdf_falha(self):
        bons = [apoio.pdf(self.pasta / f"doc{i}.pdf") for i in (1, 2)]
        ruim = apoio.pdf(self.pasta / "quebrado.pdf", b"nao e pdf")
        pares = plan_batch([bons[0], ruim, bons[1]])
        progresso = []
        resultados = sign_batch(
            load_a1(self.cert, apoio.SENHA),
            pares,
            SignatureOptions(),
            progress=lambda i, n, src: progresso.append((i, n, src.name)),
        )
        self.assertEqual([p[:2] for p in progresso], [(1, 3), (2, 3), (3, 3)])
        self.assertEqual([r.error is None for r in resultados], [True, False, True])
        self.assertIn("Não foi possível ler o PDF", resultados[1].error)
        for r in (resultados[0], resultados[2]):
            self.assertTrue(apoio.assinatura_valida(r.result.path))


if __name__ == "__main__":
    unittest.main()
