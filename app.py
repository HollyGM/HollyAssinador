from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import settings
    from signer_core import (
        SignatureOptions,
        SigningError,
        SigningResult,
        sign_pdf_a1,
        sign_pdf_a3,
    )
except ImportError as exc:
    raise SystemExit(
        "Dependências não instaladas. Execute ./build_macos.sh ou "
        "'python3 -m pip install -r requirements.txt'."
    ) from exc


APP_TITLE = "HollyAssinador"

APPEARANCES = {
    "invisible": "Invisível: sem carimbo no PDF (padrão)",
    "footer": "Carimbo no rodapé da última página, em área livre",
}


class AssinadorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)

        self.pdf_in = tk.StringVar()
        self.pdf_out = tk.StringVar()
        self.cert_type = tk.StringVar(value="A1")

        self.a1_file = tk.StringVar()
        self.a1_password = tk.StringVar()

        self.a3_module = tk.StringVar()
        self.a3_token_label = tk.StringVar()
        self.a3_cert_label = tk.StringVar()
        self.a3_key_label = tk.StringVar()
        self.a3_pin = tk.StringVar()

        self.reason = tk.StringVar(value="Assinatura digital")
        self.location = tk.StringVar()
        self.tsa_url = tk.StringVar()
        self.appearance = tk.StringVar(value="invisible")
        self.appearance_label = tk.StringVar(value=APPEARANCES["invisible"])
        self.status = tk.StringVar(value="Pronto.")

        # Campos lembrados entre execuções (nunca a senha do A1 nem o PIN do A3).
        self._remembered = {
            "cert_type": self.cert_type,
            "a1_file": self.a1_file,
            "a3_module": self.a3_module,
            "a3_token_label": self.a3_token_label,
            "a3_cert_label": self.a3_cert_label,
            "a3_key_label": self.a3_key_label,
            "reason": self.reason,
            "location": self.location,
            "tsa_url": self.tsa_url,
            "appearance": self.appearance,
        }
        for key, value in settings.load().items():
            self._remembered[key].set(value)
        self.appearance_label.set(APPEARANCES[self.appearance.get()])
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build_ui()
        self._fit_window()

    def _fit_window(self):
        # A altura que o Tk exige varia com a versão (o Tk 9 usa linhas maiores),
        # então a janela é dimensionada pelo conteúdo, tomando o formulário A3,
        # que é o mais alto, como referência.
        initial = self.cert_type.get()
        self.cert_type.set("A3")
        self._toggle_cert_frames()
        self.update_idletasks()
        width = max(760, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        self.cert_type.set(initial)
        self._toggle_cert_frames()
        self.geometry(f"{width}x{height}")
        self.minsize(self.winfo_reqwidth(), height)

    def _appearance_selected(self, _event=None):
        label = self.appearance_label.get()
        for key, text in APPEARANCES.items():
            if text == label:
                self.appearance.set(key)

    def _save_settings(self):
        try:
            settings.save({key: var.get() for key, var in self._remembered.items()})
        except OSError:
            pass  # lembrar as preferências nunca pode impedir uma assinatura

    def _close(self):
        self._save_settings()
        self.destroy()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(outer, text="Assinador Digital para macOS",
                  font=("Helvetica", 20, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Assinatura criptográfica PAdES em PDF com certificados A1 ou A3.",
        ).pack(anchor="w", pady=(0, 14))

        files_box = ttk.LabelFrame(outer, text="Documento")
        files_box.pack(fill="x", pady=(0, 10))
        files_box.columnconfigure(1, weight=1)

        ttk.Label(files_box, text="PDF de entrada").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files_box, textvariable=self.pdf_in).grid(
            row=0, column=1, sticky="ew", **pad
        )
        ttk.Button(files_box, text="Abrir…", command=self._choose_pdf).grid(
            row=0, column=2, **pad
        )

        ttk.Label(files_box, text="PDF assinado").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(files_box, textvariable=self.pdf_out).grid(
            row=1, column=1, sticky="ew", **pad
        )
        ttk.Button(files_box, text="Salvar como…", command=self._choose_output).grid(
            row=1, column=2, **pad
        )

        cert_box = ttk.LabelFrame(outer, text="Certificado")
        cert_box.pack(fill="x", pady=(0, 10))

        choose = ttk.Frame(cert_box)
        choose.pack(fill="x", padx=12, pady=(10, 2))
        ttk.Radiobutton(
            choose, text="A1 (.p12 / .pfx)", variable=self.cert_type,
            value="A1", command=self._toggle_cert_frames
        ).pack(side="left")
        ttk.Radiobutton(
            choose, text="A3 (token/cartão PKCS#11)", variable=self.cert_type,
            value="A3", command=self._toggle_cert_frames
        ).pack(side="left", padx=(20, 0))

        self.a1_frame = ttk.Frame(cert_box)
        self.a1_frame.columnconfigure(1, weight=1)

        ttk.Label(self.a1_frame, text="Certificado").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.a1_frame, textvariable=self.a1_file).grid(
            row=0, column=1, sticky="ew", **pad
        )
        ttk.Button(self.a1_frame, text="Selecionar…", command=self._choose_a1).grid(
            row=0, column=2, **pad
        )
        ttk.Label(self.a1_frame, text="Senha").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(self.a1_frame, textvariable=self.a1_password, show="•").grid(
            row=1, column=1, sticky="ew", **pad
        )

        self.a3_frame = ttk.Frame(cert_box)
        self.a3_frame.columnconfigure(1, weight=1)

        ttk.Label(self.a3_frame, text="Módulo PKCS#11").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.a3_frame, textvariable=self.a3_module).grid(
            row=0, column=1, sticky="ew", **pad
        )
        ttk.Button(self.a3_frame, text="Selecionar…", command=self._choose_pkcs11).grid(
            row=0, column=2, **pad
        )
        ttk.Label(self.a3_frame, text="Token label").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(self.a3_frame, textvariable=self.a3_token_label).grid(
            row=1, column=1, sticky="ew", **pad
        )
        ttk.Label(self.a3_frame, text="Certificate label").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(self.a3_frame, textvariable=self.a3_cert_label).grid(
            row=2, column=1, sticky="ew", **pad
        )
        ttk.Label(self.a3_frame, text="Key label (opcional)").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(self.a3_frame, textvariable=self.a3_key_label).grid(
            row=3, column=1, sticky="ew", **pad
        )
        ttk.Label(self.a3_frame, text="PIN").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(self.a3_frame, textvariable=self.a3_pin, show="•").grid(
            row=4, column=1, sticky="ew", **pad
        )

        meta_box = ttk.LabelFrame(outer, text="Dados da assinatura")
        meta_box.pack(fill="x", pady=(0, 10))
        meta_box.columnconfigure(1, weight=1)

        ttk.Label(meta_box, text="Motivo").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(meta_box, textvariable=self.reason).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(meta_box, text="Local").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(meta_box, textvariable=self.location).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(meta_box, text="TSA (opcional)").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(meta_box, textvariable=self.tsa_url).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Label(meta_box, text="Aparência").grid(row=3, column=0, sticky="w", **pad)
        appearance_box = ttk.Combobox(
            meta_box,
            textvariable=self.appearance_label,
            values=list(APPEARANCES.values()),
            state="readonly",
        )
        appearance_box.grid(row=3, column=1, sticky="ew", **pad)
        appearance_box.bind("<<ComboboxSelected>>", self._appearance_selected)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Label(bottom, textvariable=self.status).pack(side="left")

        self.sign_button = ttk.Button(
            bottom, text="Assinar PDF", command=self._start_sign
        )
        self.sign_button.pack(side="right")

    def _toggle_cert_frames(self):
        if self.cert_type.get() == "A1":
            shown, hidden = self.a1_frame, self.a3_frame
        else:
            shown, hidden = self.a3_frame, self.a1_frame
        hidden.pack_forget()
        shown.pack(fill="x", padx=4, pady=4)

    def _choose_pdf(self):
        value = filedialog.askopenfilename(
            title="Selecione o PDF",
            filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")]
        )
        if value:
            self.pdf_in.set(value)
            p = Path(value)
            self.pdf_out.set(str(p.with_name(p.stem + "-assinado.pdf")))

    def _choose_output(self):
        value = filedialog.asksaveasfilename(
            title="Salvar PDF assinado",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if value:
            self.pdf_out.set(value)

    def _choose_a1(self):
        value = filedialog.askopenfilename(
            title="Selecione o certificado A1",
            filetypes=[
                ("PKCS#12", "*.p12 *.pfx"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if value:
            self.a1_file.set(value)

    def _choose_pkcs11(self):
        value = filedialog.askopenfilename(
            title="Selecione o módulo PKCS#11 do fabricante",
            filetypes=[
                ("Biblioteca macOS", "*.dylib"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if value:
            self.a3_module.set(value)

    def _start_sign(self):
        if not self.pdf_in.get().strip() or not self.pdf_out.get().strip():
            messagebox.showerror(APP_TITLE, "Selecione o PDF de entrada e o arquivo de saída.")
            return

        self.sign_button.configure(state="disabled")
        self.status.set("Assinando…")
        self._save_settings()

        # Os valores são lidos aqui, na thread principal; o worker não toca no Tk.
        opts = SignatureOptions(
            reason=self.reason.get().strip(),
            location=self.location.get().strip(),
            tsa_url=self.tsa_url.get().strip(),
            appearance=self.appearance.get(),
        )
        job = {
            "type": self.cert_type.get(),
            "pdf_in": self.pdf_in.get(),
            "pdf_out": self.pdf_out.get(),
            "a1_file": self.a1_file.get(),
            "a1_password": self.a1_password.get(),
            "a3_module": self.a3_module.get(),
            "a3_token_label": self.a3_token_label.get(),
            "a3_cert_label": self.a3_cert_label.get(),
            "a3_key_label": self.a3_key_label.get(),
            "a3_pin": self.a3_pin.get(),
        }
        thread = threading.Thread(target=self._sign_worker, args=(job, opts), daemon=True)
        thread.start()

    def _sign_worker(self, job: dict, opts: SignatureOptions):
        try:
            if job["type"] == "A1":
                result = sign_pdf_a1(
                    job["pdf_in"],
                    job["pdf_out"],
                    job["a1_file"],
                    job["a1_password"],
                    opts,
                )
            else:
                result = sign_pdf_a3(
                    job["pdf_in"],
                    job["pdf_out"],
                    job["a3_module"],
                    job["a3_token_label"],
                    job["a3_cert_label"],
                    job["a3_key_label"],
                    job["a3_pin"],
                    opts,
                )

            self.after(0, lambda: self._success(result))
        except SigningError as exc:
            self.after(0, lambda e=str(exc): self._error(e))
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._error(e))

    def _success(self, result: SigningResult):
        self.sign_button.configure(state="normal")
        self.status.set("Assinatura concluída.")
        message = f"PDF assinado com sucesso:\n\n{result.path}"
        if result.notes:
            message += "\n\nAtenção:\n" + "\n".join(result.notes)
        messagebox.showinfo(APP_TITLE, message)

    def _error(self, message: str):
        self.sign_button.configure(state="normal")
        self.status.set("Falha na assinatura.")
        messagebox.showerror(APP_TITLE, message)


def main():
    if "--self-test" in sys.argv:
        import selftest

        raise SystemExit(selftest.run())
    app = AssinadorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
