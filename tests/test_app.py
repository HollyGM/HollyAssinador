"""Testes da janela (Tk), com o cadastro redirecionado para uma pasta temporária.

Os diálogos (messagebox, filedialog) são substituídos por dublês, então nada
espera clique. Uma única janela serve a todos os testes: no macOS, criar um
segundo Tk no mesmo processo derruba o Python. Sem tela, os testes são pulados.
"""
from __future__ import annotations

import json
import tempfile
import tkinter
import unittest
from pathlib import Path
from unittest import mock

from tests import apoio
import app
import settings

_JANELA = None
_PASTA_CONFIG = tempfile.TemporaryDirectory()
CONFIG = Path(_PASTA_CONFIG.name) / "config.json"
_PATCH_CONFIG = mock.patch.object(settings, "SETTINGS_PATH", CONFIG)


def setUpModule():
    global _JANELA
    _PATCH_CONFIG.start()
    try:
        _JANELA = app.AssinadorApp()
    except tkinter.TclError:
        _JANELA = None
        return
    _JANELA.withdraw()


def tearDownModule():
    if _JANELA is not None:
        _JANELA.destroy()
    _PATCH_CONFIG.stop()
    _PASTA_CONFIG.cleanup()


class JanelaTests(unittest.TestCase):
    def setUp(self):
        if _JANELA is None:
            self.skipTest("sem tela para abrir janelas Tk")
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(app.messagebox, "showinfo"),
            mock.patch.object(app.messagebox, "showwarning"),
            mock.patch.object(app.messagebox, "showerror"),
            mock.patch.object(app.messagebox, "askyesno", return_value=True),
        ]
        for p in self._patches:
            p.start()
        self.janela = j = _JANELA
        # estado inicial da janela, como se tivesse acabado de abrir
        j.cert_type.set("A1")
        j._toggle_cert_frames()
        j.a1_file.set(str(apoio.a1(self.pasta)))
        j.a1_password.set(apoio.SENHA)
        for var in (j.a3_module, j.a3_token_label, j.a3_cert_label, j.a3_key_label, j.a3_pin):
            var.set("")
        j.tsa_url.set("")
        j.appearance.set("invisible")
        j.last_outputs = []
        j.finder_button.configure(state="disabled")
        j.status.set("Pronto.")

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def assinar_e_esperar(self, limite_ms=60000):
        """Clica em Assinar e roda o laço de eventos real até aparecer um diálogo."""
        j = self.janela
        dialogos = (
            app.messagebox.showinfo,
            app.messagebox.showwarning,
            app.messagebox.showerror,
        )

        def conferir():
            if any(d.called for d in dialogos):
                j.quit()
            else:
                j.after(20, conferir)

        limite = j.after(limite_ms, j.quit)
        j.after(0, j._start_sign)
        j.after(20, conferir)
        j.mainloop()
        j.after_cancel(limite)
        if not any(d.called for d in dialogos):
            self.fail("a assinatura não terminou a tempo")

    @staticmethod
    def mensagem(dialogo):
        return dialogo.call_args.args[1]

    def test_um_pdf_assina_limpa_a_senha_e_libera_o_finder(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        destino = src.resolve().with_name("peticao-assinado.pdf")
        self.janela._set_inputs([str(src)])
        self.assertEqual(self.janela.pdf_out.get(), str(destino))
        self.assertEqual(str(self.janela.finder_button["state"]), "disabled")

        self.assinar_e_esperar()

        app.messagebox.showinfo.assert_called_once()
        self.assertTrue(apoio.assinatura_valida(destino))
        self.assertEqual(self.janela.a1_password.get(), "")
        self.assertEqual(str(self.janela.finder_button["state"]), "normal")
        self.assertEqual(self.janela.last_outputs, [destino])

    def test_senha_e_pin_nunca_vao_para_o_cadastro(self):
        self.janela.a3_pin.set("PIN-SECRETO")
        self.janela._set_inputs([str(apoio.pdf(self.pasta / "a.pdf"))])
        self.assinar_e_esperar()
        conteudo = CONFIG.read_text(encoding="utf-8")
        self.assertNotIn(apoio.SENHA, json.loads(conteudo).values())
        self.assertNotIn("PIN-SECRETO", conteudo)

    def test_lote_assina_todos_ao_lado_dos_originais(self):
        pdfs = [apoio.pdf(self.pasta / f"doc{i}.pdf") for i in range(3)]
        self.janela._set_inputs([str(p) for p in pdfs])
        self.assertEqual(str(self.janela.in_entry["state"]), "readonly")
        self.assertEqual(self.janela.sign_button["text"], "Assinar 3 PDFs")

        self.assinar_e_esperar()

        self.assertIn("3 de 3 PDFs assinados", self.mensagem(app.messagebox.showinfo))
        for p in pdfs:
            self.assertTrue(apoio.assinatura_valida(p.resolve().with_name(f"{p.stem}-assinado.pdf")))

    def test_lote_em_pasta_escolhida_e_com_um_pdf_quebrado(self):
        bons = [apoio.pdf(self.pasta / f"doc{i}.pdf") for i in range(2)]
        ruim = apoio.pdf(self.pasta / "quebrado.pdf", b"nao e pdf")
        destino = self.pasta / "assinados"
        self.janela._set_inputs([str(bons[0]), str(ruim), str(bons[1])])
        with mock.patch.object(app.filedialog, "askdirectory", return_value=str(destino)):
            self.janela._choose_output()

        self.assinar_e_esperar()

        mensagem = self.mensagem(app.messagebox.showwarning)
        self.assertIn("2 de 3 PDFs assinados", mensagem)
        self.assertIn("quebrado.pdf", mensagem)
        for p in bons:
            self.assertTrue(apoio.assinatura_valida(destino / f"{p.stem}-assinado.pdf"))

    def test_voltar_de_lote_para_um_pdf(self):
        pdfs = [apoio.pdf(self.pasta / f"doc{i}.pdf") for i in range(2)]
        self.janela._set_inputs([str(p) for p in pdfs])
        self.janela._set_inputs([str(pdfs[0])])
        self.assertEqual(self.janela.batch_files, [])
        self.assertEqual(str(self.janela.in_entry["state"]), "normal")
        self.assertEqual(self.janela.sign_button["text"], "Assinar PDF")
        self.assertEqual(self.janela.out_button["text"], "Salvar como…")

    def test_pergunta_antes_de_substituir_e_respeita_o_nao(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        existente = self.pasta / "peticao-assinado.pdf"
        existente.write_bytes(b"versao anterior")
        self.janela._set_inputs([str(src)])
        app.messagebox.askyesno.return_value = False

        self.janela._start_sign()
        self.janela.update()

        app.messagebox.askyesno.assert_called_once()
        self.assertEqual(existente.read_bytes(), b"versao anterior")
        self.assertEqual(self.janela.status.get(), "Pronto.")

    def test_nao_pergunta_de_novo_se_o_salvar_como_ja_confirmou(self):
        src = apoio.pdf(self.pasta / "peticao.pdf")
        existente = self.pasta / "outro-nome.pdf"
        existente.write_bytes(b"versao anterior")
        self.janela._set_inputs([str(src)])
        with mock.patch.object(app.filedialog, "asksaveasfilename", return_value=str(existente)):
            self.janela._choose_output()

        self.assinar_e_esperar()

        app.messagebox.askyesno.assert_not_called()
        self.assertTrue(apoio.assinatura_valida(existente))

    def test_saida_igual_ao_original_avisa_sem_perguntar_nada(self):
        src = apoio.pdf(self.pasta / "Contrato.pdf")
        self.janela._set_inputs([str(src)])
        self.janela.pdf_out.set(str(src))
        self.janela._start_sign()
        app.messagebox.askyesno.assert_not_called()
        self.assertIn("diferente do PDF original", self.mensagem(app.messagebox.showerror))

    def test_pin_e_limpo_mesmo_quando_a_assinatura_falha(self):
        self.janela.cert_type.set("A3")
        self.janela.a3_module.set(str(self.pasta / "nao-existe.dylib"))
        self.janela.a3_cert_label.set("cert")
        self.janela.a3_pin.set("1234")
        self.janela._set_inputs([str(apoio.pdf(self.pasta / "a.pdf"))])

        self.assinar_e_esperar()

        self.assertIn("Módulo PKCS#11 não encontrado", self.mensagem(app.messagebox.showerror))
        self.assertEqual(self.janela.a3_pin.get(), "")
        self.assertEqual(str(self.janela.sign_button["state"]), "normal")

    def test_mostrar_no_finder(self):
        assinado = apoio.pdf(self.pasta / "x-assinado.pdf")
        self.janela.last_outputs = [assinado]
        with mock.patch.object(app.subprocess, "Popen") as popen:
            self.janela._reveal()
        popen.assert_called_once_with(["open", "-R", str(assinado)])


if __name__ == "__main__":
    unittest.main()
