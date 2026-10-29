"""Small Windows UI for the local language switcher; standard library only."""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import patcher


class Launcher(tk.Tk):
    def __init__(self, game_dir: str | None = None, auto_action: str | None = None):
        super().__init__()
        self.title("Griffin — idioma del cliente")
        self.geometry("620x350")
        self.minsize(560, 320)
        self.maxsize(900, 560)
        candidates = patcher.find_game_dirs()
        default = next((p for p in candidates if str(p).lower().startswith("d:\\")),
                       candidates[0] if candidates else Path(r"C:\Program Files\GF2Exilium\GF2 Game"))
        self.game_dir = tk.StringVar(value=game_dir or str(default))
        self.status_text = tk.StringVar(value="Detecta la instalación y comprueba sus hashes antes de escribir.")
        self.busy = False
        self.buttons = []
        self._build()
        if auto_action:
            # started again with administrator rights to finish what the user asked for
            self.after(400, lambda: self._run(auto_action))

    def _build(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Carpeta del juego", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(6, 14))
        ttk.Entry(row, textvariable=self.game_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Elegir…", command=self._browse).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="Idioma (el juego debe estar cerrado)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=8)
        for label, locale in (("中文 · Restaurar", "cn"), ("English", "en"), ("Español", "es")):
            button = ttk.Button(buttons, text=label, command=lambda lang=locale: self._run(lang))
            button.pack(
                side="left", fill="x", expand=True, padx=(0, 8))
            self.buttons.append(button)
        check_button = ttk.Button(frame, text="Comprobar estado", command=lambda: self._run("status"))
        check_button.pack(anchor="w", pady=(4, 10))
        self.buttons.append(check_button)
        ttk.Separator(frame).pack(fill="x", pady=6)
        result_frame = ttk.Frame(frame)
        result_frame.pack(fill="both", expand=True, pady=(6, 8))
        self.result = tk.Text(result_frame, height=7, wrap="word", font=("Segoe UI", 10),
                              relief="flat", background="#f3f5f7", padx=8, pady=6)
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.result.yview)
        self.result.configure(yscrollcommand=scrollbar.set, state="disabled")
        self.result.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._show_result(self.status_text.get())
        admin = "Se ejecuta como administrador. " if patcher.is_admin() else "Pedirá permisos de administrador si la carpeta del juego está protegida (C:\\Program Files). "
        ttk.Label(frame, text=admin + "No altera ejecutables ni tablas del servidor.",
                  foreground="#555", wraplength=580, justify="left").pack(anchor="w", side="bottom")

    def _browse(self):
        selected = filedialog.askdirectory(title="Selecciona la carpeta del juego")
        if selected:
            self.game_dir.set(selected)

    def _run(self, action: str):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")

        def work():
            try:
                if action == "status":
                    result = patcher.status(Path(self.game_dir.get()))
                else:
                    result = patcher.apply_language(Path(self.game_dir.get()), action)
                summary = self._format_result(action, result)
                self.after(0, lambda: self._finish(summary))
            except patcher.ElevationRequired as exc:
                if patcher.is_admin():
                    message = str(exc)
                    self.after(0, lambda message=message: self._fail(message))
                else:
                    self.after(0, lambda: self._elevate(action))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda message=message: self._fail(message))
        self.status_text.set("Preparando traducciones y verificando…")
        threading.Thread(target=work, daemon=True).start()

    def _elevate(self, action: str):
        """The folder is protected: start this window again with administrator rights (UAC) and run the same action there."""
        self._show_result("Esta carpeta necesita permisos de administrador.\nWindows va a pedirte confirmación; al aceptar se abre una ventana nueva que aplica el cambio.")
        arguments = ["--game-dir", self.game_dir.get(), "--run", action]
        if patcher.relaunch_elevated(Path(__file__).resolve(), arguments):
            self.destroy()
            return
        self._fail("No se concedieron permisos de administrador. No se cambió ningún archivo.")

    def _finish(self, summary: str):
        self.status_text.set(summary.splitlines()[0])
        self._show_result(summary)
        self._unlock()

    def _fail(self, message: str):
        self.status_text.set(message)
        self._show_result("No se aplicó ningún cambio.\n\n" + message)
        self._unlock()
        messagebox.showerror("No se aplicó", message)

    def _show_result(self, message: str):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", message)
        self.result.configure(state="disabled")

    @staticmethod
    def _format_result(action: str, result: dict) -> str:
        if action == "status":
            language_names = {"cn": "Chino", "en": "English", "es": "Español",
                              "unknown/modified": "Desconocido o modificado"}
            lines = ["Estado comprobado correctamente.",
                     f"Build detectado: {result['profile']}.",
                     f"Idioma: {language_names.get(result['locale'], result['locale'])}.",
                     f"Juego abierto: {'sí' if result['game_running'] else 'no'}.",
                     f"Se puede escribir sin administrador: {'sí' if result['write_access'] else 'no'}."]
            if result.get("client_normalized_builtin"):
                lines.append("El cliente reajustó la tabla incorporada; puedes reaplicar el idioma o restaurar chino.")
            if not result["write_access"]:
                lines.append("Windows protege esta carpeta: al aplicar un idioma se pedirán permisos de administrador.")
            return "\n".join(lines)

        language_names = {"cn": "Chino restaurado", "en": "English aplicado", "es": "Español aplicado"}
        lines = [f"{language_names[action]} correctamente.",
                 f"Build: {result['profile']}.",
                 "Las tablas CN originales quedaron respaldadas y se pueden restaurar con «Chino · Restaurar»."]
        coverage = result.get("coverage")
        if coverage:
            translated = f"{coverage['translated']:,}".replace(",", ".")
            total = f"{coverage['target_rows']:,}".replace(",", ".")
            fallback = f"{coverage['fallback_cn']:,}".replace(",", ".")
            official = f"{coverage.get('official_translated', translated):,}".replace(",", ".")
            machine = f"{coverage.get('machine_translated', 0):,}".replace(",", ".")
            empty = f"{coverage.get('empty_rows', 0):,}".replace(",", ".")
            percent = f"{100 * coverage['translated'] / max(coverage['target_rows'], 1):.1f}".replace(".", ",")
            builtin_official = f"{coverage.get('builtin_official', coverage['builtin_translated']):,}".replace(",", ".")
            builtin_machine = f"{coverage.get('builtin_machine', 0):,}".replace(",", ".")
            lines.extend((f"Filas principales traducidas: {translated} de {total} ({percent}%).",
                          f"Fuente oficial: {official}; traducción automática local: {machine}.",
                          f"Textos incorporados: {builtin_official} oficiales + {builtin_machine} automáticos.",
                          f"Aún en chino: {fallback}; filas vacías: {empty}.",
                          "El cambio se verificó y no alteró IDs ni otras columnas."))
        return "\n".join(lines)

    def _unlock(self):
        self.busy = False
        for button in self.buttons:
            button.configure(state="normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", default=None)
    parser.add_argument("--run", choices=("cn", "en", "es", "status"), default=None)
    options = parser.parse_args()
    Launcher(options.game_dir, options.run).mainloop()
