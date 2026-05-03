#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
import json
import logging
from pathlib import Path
import queue
import socket
import subprocess
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from starbridge import HomeAgent, generate_configs


class QueueLogHandler(logging.Handler):
    def __init__(self, sink: "queue.Queue[str]") -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.put(self.format(record))


@dataclass
class AgentConfig:
    relay_host: str
    relay_port: int
    token: str
    use_tls: bool
    ca_file: str | None
    retry_seconds: int
    relay_bind_host: str | None
    egress_bind_host: str | None
    verbose: bool


def tcp_probe(host: str, port: int, bind_host: str | None, timeout: float = 4.0) -> tuple[bool, str]:
    source = (bind_host, 0) if bind_host else None
    try:
        with socket.create_connection((host, port), timeout=timeout, source_address=source):
            return True, "ok"
    except Exception as exc:
        return False, str(exc)


class HomeAgentRunner:
    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        self.log_queue = log_queue
        self._stop_signal = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._log_handler: QueueLogHandler | None = None

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, cfg: AgentConfig) -> bool:
        with self._lock:
            if self.is_running():
                return False
            self._stop_signal.clear()
            thread = threading.Thread(
                target=self._thread_main,
                args=(cfg,),
                daemon=True,
                name="HomeAgentRunner",
            )
            self._thread = thread
            thread.start()
            return True

    def stop(self, timeout: float = 8.0) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_signal.set()
        thread.join(timeout=timeout)

    def _thread_main(self, cfg: AgentConfig) -> None:
        self._attach_logger(cfg.verbose)
        try:
            asyncio.run(self._run_loop(cfg))
        except Exception as exc:
            self.log_queue.put(f"[GUI] agent thread crashed: {exc}")
        finally:
            self._detach_logger()
            self.log_queue.put("__AGENT_EXIT__")

    async def _run_loop(self, cfg: AgentConfig) -> None:
        agent = HomeAgent(
            relay_host=cfg.relay_host,
            relay_port=cfg.relay_port,
            token=cfg.token,
            use_tls=cfg.use_tls,
            ca_file=cfg.ca_file,
            retry_seconds=cfg.retry_seconds,
            relay_bind_host=cfg.relay_bind_host,
            egress_bind_host=cfg.egress_bind_host,
        )
        task = asyncio.create_task(agent.run_forever())
        try:
            while not self._stop_signal.is_set():
                await asyncio.sleep(0.25)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _attach_logger(self, verbose: bool) -> None:
        logger = logging.getLogger("starbridge")
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        logger.propagate = False
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        self._log_handler = handler
        logger.addHandler(handler)

    def _detach_logger(self) -> None:
        logger = logging.getLogger("starbridge")
        handler = self._log_handler
        if handler:
            logger.removeHandler(handler)
            handler.close()
        self._log_handler = None


class StarBridgeGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("StarBridge Control Center")
        self.root.geometry("980x820")
        self.root.configure(bg="#111318")

        self.bg_main = "#111318"
        self.bg_panel = "#1a1f2b"
        self.bg_input = "#252b39"
        self.fg_main = "#e8ecf3"
        self.fg_muted = "#aeb6c7"
        self.accent = "#4ea1ff"
        self.accent_active = "#6cb3ff"
        self.border = "#2c3446"

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.runner = HomeAgentRunner(self.log_queue)
        self.profiles: list[dict] = []

        self.relay_host_var = tk.StringVar(value="YOUR_RELAY_HOST")
        self.relay_port_var = tk.StringVar(value="9443")
        self.token_var = tk.StringVar(value="CHANGE_THIS_TOKEN")
        self.no_tls_var = tk.BooleanVar(value=False)
        self.ca_file_var = tk.StringVar(value="")
        self.retry_var = tk.StringVar(value="5")
        self.relay_bind_host_var = tk.StringVar(value="")
        self.egress_bind_host_var = tk.StringVar(value="")
        self.verbose_var = tk.BooleanVar(value=True)

        self.count_var = tk.StringVar(value="20")
        self.start_port_var = tk.StringVar(value="9443")
        self.prefix_var = tk.StringVar(value="sb")
        self.token_bytes_var = tk.StringVar(value="18")
        self.output_dir_var = tk.StringVar(value="generated-configs")
        self.listen_host_var = tk.StringVar(value="127.0.0.1")
        self.listen_port_var = tk.StringVar(value="1080")
        self.auto_add_active_var = tk.BooleanVar(value=True)

        self.network_status_var = tk.StringVar(value="Not checked")
        self._network_check_lock = threading.Lock()
        self._network_check_running = False

        self.style = ttk.Style()
        self._apply_dark_theme()
        self._build_ui()
        self.root.after(150, self._flush_logs)
        self.root.after(300, self.refresh_network_status)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self) -> None:
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure(".", background=self.bg_main, foreground=self.fg_main)
        self.style.configure("TFrame", background=self.bg_main)
        self.style.configure("TLabelframe", background=self.bg_panel, bordercolor=self.border)
        self.style.configure("TLabelframe.Label", background=self.bg_panel, foreground=self.fg_main)
        self.style.configure("TLabel", background=self.bg_main, foreground=self.fg_main)
        self.style.configure("TCheckbutton", background=self.bg_main, foreground=self.fg_main)
        self.style.map(
            "TCheckbutton",
            background=[("active", self.bg_main), ("selected", self.bg_main)],
            foreground=[("disabled", self.fg_muted)],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=self.bg_input,
            foreground=self.fg_main,
            insertcolor=self.fg_main,
            bordercolor=self.border,
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("disabled", "#1d2230"), ("readonly", "#1f2533")],
            foreground=[("disabled", self.fg_muted)],
        )
        self.style.configure(
            "TButton",
            background=self.accent,
            foreground="#081225",
            bordercolor=self.accent,
            focusthickness=0,
            padding=6,
        )
        self.style.map(
            "TButton",
            background=[("active", self.accent_active), ("pressed", "#3b8de8")],
            foreground=[("disabled", self.fg_muted)],
        )

    def _apply_text_widget_theme(self, widget: tk.Text) -> None:
        widget.configure(
            background=self.bg_input,
            foreground=self.fg_main,
            insertbackground=self.fg_main,
            selectbackground=self.accent,
            selectforeground="#081225",
            highlightbackground=self.border,
            highlightcolor=self.accent,
        )

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        agent_group = ttk.LabelFrame(frame, text="Home Agent")
        agent_group.pack(fill="x", pady=(0, 8))
        form = ttk.Frame(agent_group, padding=8)
        form.pack(fill="x")

        self._entry_row(form, 0, "Relay Host", self.relay_host_var, 34, 0, 1)
        self._entry_row(form, 0, "Relay Port", self.relay_port_var, 10, 2, 3)
        self._entry_row(form, 1, "Token", self.token_var, 34, 0, 1)
        self._entry_row(form, 1, "Retry (sec)", self.retry_var, 10, 2, 3)
        self._entry_row(form, 2, "CA File", self.ca_file_var, 34, 0, 1)
        ttk.Checkbutton(form, text="Disable TLS", variable=self.no_tls_var).grid(
            row=2, column=2, sticky="w", padx=6, pady=4
        )
        ttk.Checkbutton(form, text="Verbose logs", variable=self.verbose_var).grid(
            row=2, column=3, sticky="w", padx=6, pady=4
        )
        self._entry_row(form, 3, "Relay Bind IP", self.relay_bind_host_var, 34, 0, 1)
        self._entry_row(form, 3, "Egress Bind IP", self.egress_bind_host_var, 20, 2, 3)
        for col in (1, 3):
            form.columnconfigure(col, weight=1)

        actions = ttk.Frame(agent_group, padding=(8, 0, 8, 8))
        actions.pack(fill="x")
        self.start_btn = ttk.Button(actions, text="Start Agent", command=self.start_agent)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="Stop Agent", command=self.stop_agent, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Checkbutton(actions, text="Add Active Config To List", variable=self.auto_add_active_var).pack(
            side="left", padx=10
        )
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=16)

        network_group = ttk.LabelFrame(frame, text="Network Status")
        network_group.pack(fill="x", pady=(0, 8))
        network_actions = ttk.Frame(network_group, padding=(8, 8, 8, 0))
        network_actions.pack(fill="x")
        ttk.Button(network_actions, text="Refresh Adapters", command=self.refresh_network_status).pack(
            side="left"
        )
        ttk.Button(network_actions, text="Test Paths", command=self.test_network_paths).pack(
            side="left", padx=6
        )
        ttk.Label(network_actions, textvariable=self.network_status_var).pack(side="left", padx=14)

        self.network_box = ScrolledText(network_group, height=8, font=("Consolas", 10))
        self.network_box.pack(fill="x", padx=8, pady=(6, 8))
        self._apply_text_widget_theme(self.network_box)
        self.network_box.configure(state="disabled")

        config_group = ttk.LabelFrame(frame, text="Config Generator")
        config_group.pack(fill="both", expand=True)

        gen_form = ttk.Frame(config_group, padding=8)
        gen_form.pack(fill="x")
        self._entry_row(gen_form, 0, "Count", self.count_var, 8, 0, 1)
        self._entry_row(gen_form, 0, "Start Port", self.start_port_var, 10, 2, 3)
        self._entry_row(gen_form, 1, "Prefix", self.prefix_var, 10, 0, 1)
        self._entry_row(gen_form, 1, "Token Bytes", self.token_bytes_var, 10, 2, 3)
        self._entry_row(gen_form, 2, "Output Dir", self.output_dir_var, 34, 0, 1)
        self._entry_row(gen_form, 2, "Listen Host", self.listen_host_var, 20, 2, 3)
        self._entry_row(gen_form, 3, "Listen Port", self.listen_port_var, 10, 0, 1)
        ttk.Button(gen_form, text="Generate Configs", command=self.generate_configs_from_ui).grid(
            row=3, column=2, sticky="w", padx=6, pady=4
        )
        ttk.Button(gen_form, text="Clear List", command=self.clear_profiles).grid(
            row=3, column=3, sticky="w", padx=6, pady=4
        )
        for col in (1, 3):
            gen_form.columnconfigure(col, weight=1)

        list_frame = ttk.Frame(config_group, padding=(8, 0, 8, 8))
        list_frame.pack(fill="both", expand=True)

        left = ttk.Frame(list_frame)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(list_frame)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ttk.Label(left, text="Config List").pack(anchor="w")
        self.profile_list = tk.Listbox(left, height=12)
        self.profile_list.configure(
            background=self.bg_input,
            foreground=self.fg_main,
            selectbackground=self.accent,
            selectforeground="#081225",
            highlightthickness=1,
            highlightbackground=self.border,
            highlightcolor=self.accent,
            relief="solid",
            borderwidth=1,
        )
        self.profile_list.pack(fill="both", expand=True)
        self.profile_list.bind("<<ListboxSelect>>", self._on_profile_select)

        list_actions = ttk.Frame(left)
        list_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(list_actions, text="Copy Selected URI", command=self.copy_selected_uri).pack(side="left")

        ttk.Label(right, text="Selected Config JSON").pack(anchor="w")
        self.profile_detail = ScrolledText(right, height=12, font=("Consolas", 10))
        self.profile_detail.pack(fill="both", expand=True)
        self._apply_text_widget_theme(self.profile_detail)
        self.profile_detail.configure(state="disabled")

        ttk.Label(frame, text="Logs").pack(anchor="w")
        self.log_box = ScrolledText(frame, height=9, font=("Consolas", 10))
        self.log_box.pack(fill="both", expand=True)
        self._apply_text_widget_theme(self.log_box)
        self.log_box.configure(state="disabled")

    def _entry_row(
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

    def refresh_network_status(self) -> None:
        self._run_network_check(test_paths=False)

    def test_network_paths(self) -> None:
        self._run_network_check(test_paths=True)

    def _run_network_check(self, test_paths: bool) -> None:
        with self._network_check_lock:
            if self._network_check_running:
                self._append_log("[GUI] network check already running")
                return
            self._network_check_running = True
        self.network_status_var.set("Checking...")
        worker = threading.Thread(
            target=self._network_check_worker,
            args=(test_paths,),
            daemon=True,
            name="NetworkCheck",
        )
        worker.start()

    def _network_check_worker(self, test_paths: bool) -> None:
        try:
            report_lines: list[str] = []
            report_lines.append("Active IPv4 adapters:")
            adapters_output = self._get_adapter_summary()
            report_lines.append(adapters_output.strip())
            report_lines.append("")
            report_lines.append("Default routes:")
            routes_output = self._get_default_route_summary()
            report_lines.append(routes_output.strip())

            if test_paths:
                relay_host = self.relay_host_var.get().strip()
                relay_port_raw = self.relay_port_var.get().strip()
                relay_bind_host = self.relay_bind_host_var.get().strip() or None
                egress_bind_host = self.egress_bind_host_var.get().strip() or None
                report_lines.append("")
                report_lines.append("Path tests:")
                try:
                    relay_port = int(relay_port_raw)
                except ValueError:
                    relay_port = 0

                if relay_host and 1 <= relay_port <= 65535:
                    ok, detail = tcp_probe(relay_host, relay_port, relay_bind_host)
                    status = "OK" if ok else "FAIL"
                    report_lines.append(
                        f"- Relay path ({relay_bind_host or 'auto'} -> {relay_host}:{relay_port}): {status} ({detail})"
                    )
                else:
                    report_lines.append("- Relay path: skipped (invalid relay host/port)")

                egress_targets = [("1.1.1.1", 443), ("8.8.8.8", 443)]
                egress_ok = False
                egress_detail = ""
                for host, port in egress_targets:
                    ok, detail = tcp_probe(host, port, egress_bind_host)
                    if ok:
                        egress_ok = True
                        egress_detail = f"{host}:{port}"
                        break
                    egress_detail = detail
                status = "OK" if egress_ok else "FAIL"
                report_lines.append(
                    f"- Egress path ({egress_bind_host or 'auto'} -> internet): {status} ({egress_detail})"
                )

            text = "\n".join(report_lines).strip() + "\n"
            self.root.after(0, lambda: self._finish_network_check(text))
        except Exception as exc:
            self.root.after(0, lambda: self._finish_network_check(f"Network check failed: {exc}\n"))

    def _finish_network_check(self, report_text: str) -> None:
        self.network_box.configure(state="normal")
        self.network_box.delete("1.0", tk.END)
        self.network_box.insert("1.0", report_text)
        self.network_box.configure(state="disabled")
        self.network_status_var.set("Done")
        with self._network_check_lock:
            self._network_check_running = False

    def _get_adapter_summary(self) -> str:
        script = (
            "$items = Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address }; "
            "if (-not $items) { 'No active IPv4 adapters found.'; exit 0 }; "
            "$items | Select-Object InterfaceAlias, "
            "@{Name='IPv4';Expression={($_.IPv4Address | ForEach-Object {$_.IPAddress}) -join ', '}}, "
            "@{Name='Gateway';Expression={ if ($_.IPv4DefaultGateway) { $_.IPv4DefaultGateway.NextHop } else { '-' }}} "
            "| Format-Table -AutoSize | Out-String"
        )
        ok, output = self._run_powershell(script)
        if ok:
            return output
        return f"Failed to query adapters: {output}"

    def _get_default_route_summary(self) -> str:
        script = (
            "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 "
            "| Sort-Object RouteMetric, InterfaceMetric; "
            "if (-not $r) { 'No default IPv4 route found.'; exit 0 }; "
            "$r | Select-Object -First 6 InterfaceAlias, NextHop, RouteMetric, InterfaceMetric "
            "| Format-Table -AutoSize | Out-String"
        )
        ok, output = self._run_powershell(script)
        if ok:
            return output
        return f"Failed to query routes: {output}"

    def _run_powershell(self, script: str) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=15,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}"
            return False, err
        return True, proc.stdout.strip()

    def start_agent(self) -> None:
        if self.runner.is_running():
            return
        cfg = self._read_agent_config()
        if cfg is None:
            return
        self._append_log(
            f"[GUI] starting home-agent to {cfg.relay_host}:{cfg.relay_port} (tls={cfg.use_tls})"
        )
        if not self.runner.start(cfg):
            self._append_log("[GUI] already running")
            return
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Running")
        if self.auto_add_active_var.get():
            self._add_active_profile(cfg)

    def stop_agent(self) -> None:
        if not self.runner.is_running():
            return
        self._append_log("[GUI] stopping...")
        self.runner.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("Stopped")

    def _read_agent_config(self) -> AgentConfig | None:
        relay_host = self.relay_host_var.get().strip()
        token = self.token_var.get().strip()
        ca_file = self.ca_file_var.get().strip()
        relay_bind_host = self.relay_bind_host_var.get().strip()
        egress_bind_host = self.egress_bind_host_var.get().strip()
        if not relay_host or not token:
            self._append_log("[GUI] relay host and token are required")
            return None
        try:
            relay_port = int(self.relay_port_var.get().strip())
            retry_seconds = int(self.retry_var.get().strip())
        except ValueError:
            self._append_log("[GUI] relay port and retry must be numbers")
            return None
        if relay_port < 1 or relay_port > 65535:
            self._append_log("[GUI] relay port out of range")
            return None
        if retry_seconds < 1:
            self._append_log("[GUI] retry must be >= 1")
            return None
        return AgentConfig(
            relay_host=relay_host,
            relay_port=relay_port,
            token=token,
            use_tls=not self.no_tls_var.get(),
            ca_file=ca_file or None,
            retry_seconds=retry_seconds,
            relay_bind_host=relay_bind_host or None,
            egress_bind_host=egress_bind_host or None,
            verbose=self.verbose_var.get(),
        )

    def _add_active_profile(self, cfg: AgentConfig) -> None:
        profile = {
            "name": "active-current",
            "relay_host": cfg.relay_host,
            "relay_port": cfg.relay_port,
            "token": cfg.token,
            "use_tls": cfg.use_tls,
            "ca_file": cfg.ca_file,
            "relay_bind_host": cfg.relay_bind_host,
            "egress_bind_host": cfg.egress_bind_host,
            "listen_host": self.listen_host_var.get().strip() or "127.0.0.1",
            "listen_port": int(self.listen_port_var.get().strip() or "1080"),
        }
        profile["uri"] = self._profile_uri(profile)
        self.profiles = [p for p in self.profiles if p.get("name") != "active-current"]
        self.profiles.insert(0, profile)
        self._refresh_profile_list()
        self._append_log("[GUI] active config added to list")

    def _profile_uri(self, profile: dict) -> str:
        tls_value = 1 if profile.get("use_tls") else 0
        return (
            f"starbridge://{profile.get('token')}@{profile.get('relay_host')}:"
            f"{profile.get('relay_port')}?tls={tls_value}"
        )

    def generate_configs_from_ui(self) -> None:
        relay_host = self.relay_host_var.get().strip()
        if not relay_host:
            self._append_log("[GUI] relay host is required for config generation")
            return
        try:
            args = argparse.Namespace(
                relay_host=relay_host,
                count=int(self.count_var.get().strip()),
                start_port=int(self.start_port_var.get().strip()),
                listen_host=self.listen_host_var.get().strip() or "127.0.0.1",
                listen_port=int(self.listen_port_var.get().strip()),
                prefix=self.prefix_var.get().strip() or "sb",
                token_bytes=int(self.token_bytes_var.get().strip()),
                no_tls=self.no_tls_var.get(),
                ca_file=self.ca_file_var.get().strip() or None,
                relay_bind_host=self.relay_bind_host_var.get().strip() or None,
                egress_bind_host=self.egress_bind_host_var.get().strip() or None,
                output_dir=self.output_dir_var.get().strip() or "generated-configs",
            )
        except ValueError:
            self._append_log("[GUI] generator numeric fields are invalid")
            return

        try:
            generate_configs(args)
        except Exception as exc:
            self._append_log(f"[GUI] config generation failed: {exc}")
            return

        self._append_log(f"[GUI] generated {args.count} configs in {args.output_dir}")
        self._load_profiles_from_output_dir(args.output_dir)

    def _load_profiles_from_output_dir(self, output_dir: str) -> None:
        bundle_path = Path(output_dir) / "profiles.json"
        if not bundle_path.exists():
            self._append_log("[GUI] profiles.json not found after generation")
            return
        try:
            payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            profiles = payload.get("profiles", [])
            if not isinstance(profiles, list):
                raise ValueError("invalid profiles list")
        except Exception as exc:
            self._append_log(f"[GUI] failed to read profiles.json: {exc}")
            return
        self.profiles = profiles
        for profile in self.profiles:
            if "uri" not in profile:
                profile["uri"] = self._profile_uri(profile)
        self._refresh_profile_list()

    def _refresh_profile_list(self) -> None:
        self.profile_list.delete(0, tk.END)
        for profile in self.profiles:
            name = profile.get("name", "unnamed")
            relay_host = profile.get("relay_host", "?")
            relay_port = profile.get("relay_port", "?")
            token = str(profile.get("token", ""))
            token_short = token[:10] + "..." if len(token) > 10 else token
            line = f"{name} | {relay_host}:{relay_port} | {token_short}"
            self.profile_list.insert(tk.END, line)
        if self.profiles:
            self.profile_list.selection_clear(0, tk.END)
            self.profile_list.selection_set(0)
            self.profile_list.activate(0)
            self._show_profile_detail(0)

    def _on_profile_select(self, _event: tk.Event) -> None:
        selected = self.profile_list.curselection()
        if not selected:
            return
        self._show_profile_detail(selected[0])

    def _show_profile_detail(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.profiles):
            return
        profile = self.profiles[idx]
        text = json.dumps(profile, ensure_ascii=True, indent=2) + "\n"
        self.profile_detail.configure(state="normal")
        self.profile_detail.delete("1.0", tk.END)
        self.profile_detail.insert("1.0", text)
        self.profile_detail.configure(state="disabled")

    def copy_selected_uri(self) -> None:
        selected = self.profile_list.curselection()
        if not selected:
            self._append_log("[GUI] no profile selected")
            return
        idx = selected[0]
        if idx < 0 or idx >= len(self.profiles):
            return
        uri = str(self.profiles[idx].get("uri", "")).strip()
        if not uri:
            self._append_log("[GUI] selected profile has no URI")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(uri)
        self.root.update()
        self._append_log("[GUI] selected URI copied to clipboard")

    def clear_profiles(self) -> None:
        self.profiles = []
        self.profile_list.delete(0, tk.END)
        self.profile_detail.configure(state="normal")
        self.profile_detail.delete("1.0", tk.END)
        self.profile_detail.configure(state="disabled")
        self._append_log("[GUI] profile list cleared")

    def _flush_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if line == "__AGENT_EXIT__":
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                self.status_var.set("Stopped")
                self._append_log("[GUI] agent stopped")
                continue
            self._append_log(line)
        self.root.after(150, self._flush_logs)

    def _append_log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_close(self) -> None:
        self.stop_agent()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = StarBridgeGUI(root)
    root.mainloop()
    del app


if __name__ == "__main__":
    main()
