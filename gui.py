#!/usr/bin/env python3

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from gtool import DEFAULT_FILE, DEFAULT_OPEN, DEFAULT_WINDOW, MODULES, open_links, run_ticket


class L2ToolApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("l2tool")
        self.minsize(980, 680)
        self.last_result = None

        self.module_vars = {
            name: tk.BooleanVar(value=name in DEFAULT_OPEN.split(","))
            for name in MODULES
        }
        self.window_var = tk.IntVar(value=DEFAULT_WINDOW)
        self.save_history_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Готово")

        self._build_ui()
        self._load_default_ticket()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(8, weight=1)

        ttk.Label(toolbar, text="Модули:").grid(row=0, column=0, sticky="w")
        for index, (name, var) in enumerate(self.module_vars.items(), start=1):
            ttk.Checkbutton(toolbar, text=name, variable=var).grid(row=0, column=index, padx=(8, 0))

        ttk.Label(toolbar, text="Окно, мин:").grid(row=0, column=5, padx=(18, 4))
        ttk.Spinbox(toolbar, from_=5, to=1440, increment=5, width=6, textvariable=self.window_var).grid(
            row=0,
            column=6,
        )
        ttk.Checkbutton(toolbar, text="Сохранять историю", variable=self.save_history_var).grid(
            row=0,
            column=7,
            padx=(14, 0),
        )

        ttk.Button(toolbar, text="Сгенерировать", command=self.generate).grid(row=0, column=9, padx=(8, 0))
        ttk.Button(toolbar, text="Открыть ссылки", command=self.open_generated_links).grid(row=0, column=10, padx=(8, 0))

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        input_frame = ttk.Frame(panes)
        output_frame = ttk.Frame(panes)
        panes.add(input_frame, weight=1)
        panes.add(output_frame, weight=1)

        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(1, weight=1)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(1, weight=1)

        ttk.Label(input_frame, text="Текст тикета").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.ticket_text = tk.Text(input_frame, wrap="word", undo=True)
        self.ticket_text.grid(row=1, column=0, sticky="nsew")
        ticket_scroll = ttk.Scrollbar(input_frame, orient="vertical", command=self.ticket_text.yview)
        ticket_scroll.grid(row=1, column=1, sticky="ns")
        self.ticket_text.configure(yscrollcommand=ticket_scroll.set)

        ttk.Label(output_frame, text="Результат").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.output_text = tk.Text(output_frame, wrap="word", state="disabled")
        self.output_text.grid(row=1, column=0, sticky="nsew")
        output_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output_text.yview)
        output_scroll.grid(row=1, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=output_scroll.set)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(10, 6))
        status.grid(row=2, column=0, sticky="ew")

    def _load_default_ticket(self):
        path = Path(DEFAULT_FILE)
        if path.exists():
            self.ticket_text.insert("1.0", path.read_text(encoding="utf-8"))
            self.status_var.set(f"Загружен {path.as_posix()}")

    def selected_modules_arg(self):
        selected = [name for name, var in self.module_vars.items() if var.get()]
        return ",".join(selected)

    def set_output(self, text):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.configure(state="disabled")

    def generate(self):
        ticket = self.ticket_text.get("1.0", tk.END).strip()
        if not ticket:
            messagebox.showwarning("l2tool", "Вставьте текст тикета.")
            return

        modules_arg = self.selected_modules_arg()
        if not modules_arg:
            messagebox.showwarning("l2tool", "Выберите хотя бы один модуль.")
            return

        try:
            result = run_ticket(
                ticket,
                input_file="<gui>",
                open_arg=modules_arg,
                window=int(self.window_var.get()),
                save_history=self.save_history_var.get(),
            )
        except Exception as exc:
            self.last_result = None
            self.set_output(str(exc))
            self.status_var.set("Ошибка")
            messagebox.showerror("l2tool", str(exc))
            return

        self.last_result = result
        self.set_output("\n".join(result.lines))
        link_count = sum(len(links) for links in result.links_by_module.values())
        self.status_var.set(f"Ссылок: {link_count}")

    def open_generated_links(self):
        if not self.last_result or not self.last_result.links_by_module:
            messagebox.showinfo("l2tool", "Сначала сгенерируйте ссылки.")
            return

        open_links(self.last_result.links_by_module)
        self.status_var.set("Ссылки открыты")


def main():
    app = L2ToolApp()
    app.mainloop()


if __name__ == "__main__":
    main()
