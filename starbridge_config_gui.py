#!/usr/bin/env python3
import argparse
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from starbridge import generate_configs


class StarBridgeConfigGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("StarBridge Config Generator")
        self.root.geometry("760x520")

        self.relay_host_var = tk.StringVar(value="relay.example.ir")
        self.count_var = tk.StringVar(value="20")
        self.start_port_var = tk.StringVar(value="9443")
        self.prefix_var = tk.StringVar(value="sb")
        self.output_dir_var = tk.StringVar(value="generated-configs")
        self.token_bytes_var = tk.StringVar(value="18")
        self.no_tls_var = tk.BooleanVar(value=True)
        self.ca_file_var = tk.StringVar(value="")
        self.relay_bind_host_var = tk.StringVar(value="")
        self.egress_bind_host_var = tk.StringVar(value="")
        self.listen_host_var = tk.StringVar(value="127.0.0.1")
        self.listen_port_var = tk.StringVar(value="1080")

        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        form = ttk.Frame(frame)
        form.pack(fill="x")

        self._row_entry(form, 0, "Relay Host", self.relay_host_var, 34, 0, 1)
        self._row_entry(form, 0, "Count", self.count_var, 8, 2, 3)

        self._row_entry(form, 1, "Start Port", self.start_port_var, 10, 0, 1)
        self._row_entry(form, 1, "Prefix", self.prefix_var, 10, 2, 3)

        self._row_entry(form, 2, "Output Dir", self.output_dir_var, 34, 0, 1)
        self._row_entry(form, 2, "Token Bytes", self.token_bytes_var, 10, 2, 3)

        self._row_entry(form, 3, "Listen Host", self.listen_host_var, 34, 0, 1)
        self._row_entry(form, 3, "Listen Port", self.listen_port_var, 10, 2, 3)

        self._row_entry(form, 4, "Relay Bind IP", self.relay_bind_host_var, 34, 0, 1)
        self._row_entry(form, 4, "Egress Bind IP", self.egress_bind_host_var, 20, 2, 3)

        self._row_entry(form, 5, "CA File", self.ca_file_var, 34, 0, 1)
        ttk.Checkbutton(form, text="Disable TLS", variable=self.no_tls_var).grid(
            row=5, column=2, sticky="w", padx=6, pady=4
        )

        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Generate 20 Configs", command=self.generate).pack(
            side="left"
        )

        self.log_box = ScrolledText(frame, height=18, font=("Consolas", 10))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _row_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        width: int,
        label_col: int,
        entry_col: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=label_col, sticky="w")
        ttk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=entry_col, sticky="we", padx=6, pady=4
        )

    def _log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def generate(self) -> None:
        relay_host = self.relay_host_var.get().strip()
        if not relay_host:
            self._log("[ERROR] Relay Host is required")
            return

        try:
            count = int(self.count_var.get().strip())
            start_port = int(self.start_port_var.get().strip())
            token_bytes = int(self.token_bytes_var.get().strip())
            listen_port = int(self.listen_port_var.get().strip())
        except ValueError:
            self._log("[ERROR] count/start_port/token_bytes/listen_port must be numbers")
            return

        args = argparse.Namespace(
            relay_host=relay_host,
            count=count,
            start_port=start_port,
            listen_host=self.listen_host_var.get().strip() or "127.0.0.1",
            listen_port=listen_port,
            prefix=self.prefix_var.get().strip() or "sb",
            token_bytes=token_bytes,
            no_tls=self.no_tls_var.get(),
            ca_file=self.ca_file_var.get().strip() or None,
            relay_bind_host=self.relay_bind_host_var.get().strip() or None,
            egress_bind_host=self.egress_bind_host_var.get().strip() or None,
            output_dir=self.output_dir_var.get().strip() or "generated-configs",
        )

        try:
            generate_configs(args)
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            return
        self._log(f"[OK] Generated {count} configs in {args.output_dir}")


def main() -> None:
    root = tk.Tk()
    app = StarBridgeConfigGUI(root)
    root.mainloop()
    del app


if __name__ == "__main__":
    main()
