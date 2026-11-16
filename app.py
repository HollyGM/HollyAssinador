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
        BatchOutcome,
        SignatureOptions,
        SigningError,
        load_a1,
        open_a3,
        output_for,
        plan_batch,
        same_file,
        sign_batch,
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

BATCH_OUTPUT_HINT = 'Na pasta de cada PDF, com "-assinado" no nome'


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

        # Lote: vários PDFs escolhidos de uma vez (vazio = um PDF só, pelos campos).
        self.batch_files: list[str] = []
        self.batch_folder = ""
        # Saída escolhida em "Salvar como…": o próprio diálogo já confirmou a substituição.
        self._confirmed_out = ""
        # PDFs assinados na última vez, para o botão "Mostrar no Finder".
        self.last_outputs: list[Path] = []

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
        self.in_entry = ttk.Entry(files_box, textvariable=self.pdf_in)
        self.in_entry.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files_box, text="Abrir…", command=self._choose_pdf).grid(
            row=0, column=2, **pad
        )

        ttk.Label(files_box, text="PDF assinado").grid(row=1, column=0, sticky="w", **pad)
        self.out_entry = ttk.Entry(files_box, textvariable=self.pdf_out)
        self.out_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.out_button = ttk.Button(
            files_box, text="Salvar como…", command=self._choose_output
        )
        self.out_button.grid(row=1, column=2, **pad)

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
        self.finder_button = ttk.Button(
            bottom, text="Mostrar no Finder", command=self._reveal, state="disabled"
        )
        self.finder_button.pack(side="right", padx=(0, 8))

    def _toggle_cert_frames(self):
        if self.cert_type.get() == "A1":
            shown, hidden = self.a1_frame, self.a3_frame
        else:
            shown, hidden = self.a3_frame, self.a1_frame
        hidden.pack_forget()
        shown.pack(fill="x", padx=4, pady=4)

    def _choose_pdf(self):
        values = filedialog.askopenfilenames(
            title="Selecione um ou mais PDFs",
            filetypes=[("PDF", "*.pdf"), ("Todos os arquivos", "*.*")]
        )
        if values:
            self._set_inputs(values)

    def _set_inputs(self, paths):
        """Um PDF: campos editáveis, como sempre. Vários: modo lote."""
        paths = [str(p) for p in paths if str(p)]
        if not paths:
            return
        self._confirmed_out = ""
        if len(paths) == 1:
            self.batch_files = []
            self.in_entry.configure(state="normal")
            self.out_entry.configure(state="normal")
            self.out_button.configure(text="Salvar como…")
            self.sign_button.configure(text="Assinar PDF")
            self.pdf_in.set(paths[0])
            self.pdf_out.set(str(output_for(paths[0])))
            return
        self.batch_files = paths
        self.batch_folder = ""
        names = ", ".join(Path(p).name for p in paths[:3])
        if len(paths) > 3:
            names += ", …"
        self.pdf_in.set(f"{len(paths)} PDFs: {names}")
        self.pdf_out.set(BATCH_OUTPUT_HINT)
        self.in_entry.configure(state="readonly")
        self.out_entry.configure(state="readonly")
        self.out_button.configure(text="Pasta…")
        self.sign_button.configure(text=f"Assinar {len(paths)} PDFs")

    def _choose_output(self):
        if self.batch_files:
            value = filedialog.askdirectory(title="Pasta para os PDFs assinados")
            if value:
                self.batch_folder = value
                self.pdf_out.set(value)
            return
        value = filedialog.asksaveasfilename(
            title="Salvar PDF assinado",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if value:
            self.pdf_out.set(value)
            self._confirmed_out = str(Path(value).expanduser().resolve())

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

    def _plan(self) -> list[tuple[Path, Path]]:
        """Pares (original, assinado) a assinar; levanta SigningError se houver problema."""
        if self.batch_files:
            return plan_batch(self.batch_files, self.batch_folder or None)
        src, dst = self.pdf_in.get().strip(), self.pdf_out.get().strip()
        if not src or not dst:
            raise SigningError("Selecione o PDF de entrada e o arquivo de saída.")
        src_path = Path(src).expanduser().resolve()
        dst_path = Path(dst).expanduser().resolve()
        if same_file(src_path, dst_path):
            raise SigningError("Escolha um arquivo de saída diferente do PDF original.")
        return [(src_path, dst_path)]

    def _confirm_overwrite(self, existing: list[Path]) -> bool:
        if len(existing) == 1:
            message = (
                f"Já existe um arquivo com este nome:\n\n{existing[0]}\n\n"
                "Substituir pelo novo PDF assinado?"
            )
        else:
            names = "\n".join(f"• {p.name}" for p in existing[:8])
            if len(existing) > 8:
                names += f"\n• … e mais {len(existing) - 8}"
            message = (
                f"Já existem {len(existing)} arquivos com estes nomes:\n\n{names}\n\n"
                "Substituir pelos novos PDFs assinados?"
            )
        return messagebox.askyesno(
            APP_TITLE, message, icon=messagebox.WARNING, default=messagebox.NO
        )

    def _clear_secrets(self):
        # Depois de cada assinatura, quem chegar ao Mac não assina sem digitar de novo.
        self.a1_password.set("")
        self.a3_pin.set("")

    def _start_sign(self):
        try:
            pairs = self._plan()
        except SigningError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        existing = [
            dst for _, dst in pairs if dst.exists() and str(dst) != self._confirmed_out
        ]
        if existing and not self._confirm_overwrite(existing):
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
            "pairs": pairs,
            "a1_file": self.a1_file.get(),
            "a1_password": self.a1_password.get(),
            "a3_module": self.a3_module.get(),
            "a3_token_label": self.a3_token_label.get(),
            "a3_cert_label": self.a3_cert_label.get(),
            "a3_key_label": self.a3_key_label.get(),
            "a3_pin": self.a3_pin.get(),
        }
        self._clear_secrets()
        thread = threading.Thread(target=self._sign_worker, args=(job, opts), daemon=True)
        thread.start()

    def _sign_worker(self, job: dict, opts: SignatureOptions):
        def progress(index: int, total: int, src: Path):
            if total > 1:
                text = f"Assinando {index} de {total}: {src.name}…"
                self.after(0, lambda: self.status.set(text))

        try:
            if job["type"] == "A1":
                signer = load_a1(job["a1_file"], job["a1_password"])
                outcomes = sign_batch(signer, job["pairs"], opts, progress)
            else:
                # O token é aberto uma vez só, mesmo num lote: o PIN vale para todos.
                with open_a3(
                    job["a3_module"],
                    job["a3_token_label"],
                    job["a3_cert_label"],
                    job["a3_key_label"],
                    job["a3_pin"],
                ) as signer:
                    outcomes = sign_batch(signer, job["pairs"], opts, progress)

            self.after(0, lambda: self._finished(outcomes))
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._error(e))

    @staticmethod
    def _error_list(failed: list[BatchOutcome]) -> str:
        return "\n".join(f"• {o.src.name}: {o.error}" for o in failed)

    @staticmethod
    def _notes(done: list[BatchOutcome], batch: bool) -> list[str]:
        by_note: dict[str, list[str]] = {}
        for outcome in done:
            for note in outcome.result.notes:
                by_note.setdefault(note, []).append(outcome.src.name)
        lines = []
        for note, names in by_note.items():
            if batch and len(names) < len(done):
                note += " (" + ", ".join(names) + ")"
            lines.append(note)
        return lines

    def _finished(self, outcomes: list[BatchOutcome]):
        self.sign_button.configure(state="normal")
        done = [o for o in outcomes if o.result is not None]
        failed = [o for o in outcomes if o.error is not None]
        self.last_outputs = [o.result.path for o in done]
        self.finder_button.configure(state="normal" if done else "disabled")

        if not done:
            if len(failed) == 1:
                self._error(failed[0].error)
            else:
                self._error("Nenhum PDF foi assinado:\n\n" + self._error_list(failed))
            return

        batch = len(outcomes) > 1
        if batch:
            summary = f"{len(done)} de {len(outcomes)} PDFs assinados."
            self.status.set(summary)
            message = summary
            if failed:
                message += "\n\nNão assinados:\n" + self._error_list(failed)
        else:
            self.status.set("Assinatura concluída.")
            message = f"PDF assinado com sucesso:\n\n{done[0].result.path}"

        notes = self._notes(done, batch)
        if notes:
            message += "\n\nAtenção:\n" + "\n".join(notes)
        if failed:
            messagebox.showwarning(APP_TITLE, message)
        else:
            messagebox.showinfo(APP_TITLE, message)

    def _error(self, message: str):
        self.sign_button.configure(state="normal")
        self.status.set("Falha na assinatura.")
        messagebox.showerror(APP_TITLE, message)

    def _reveal(self):
        existing = [p for p in self.last_outputs if p.exists()]
        if not existing:
            messagebox.showinfo(APP_TITLE, "O PDF assinado não está mais no mesmo lugar.")
            return
        # "open -R" abre a pasta no Finder com o arquivo selecionado.
        subprocess.Popen(["open", "-R", str(existing[0])])


def main():
    if "--self-test" in sys.argv:
        import selftest

        raise SystemExit(selftest.run())
    app = AssinadorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
