"""AI-AGENT Windows setup wizard — Next / Next GUI installer (no console)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "AI-AGENT 安装向导"
APP_VERSION = "1.0"
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", "C:\\")) / "AI-AGENT"
HTTP_URL = "http://localhost:3000"


def _resource_base() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_zip() -> Path | None:
    base = _resource_base()
    for name in ("AI-AGENT-package.zip",):
        p = base / name
        if p.is_file():
            return p
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for p in [exe_dir / name for name in ("AI-AGENT-package.zip",)]:
            if p.is_file():
                return p
        matches = sorted(exe_dir.glob("aiagnet-win-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    return None


class Wizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("560x420")
        self.resizable(False, False)
        self.install_dir = tk.StringVar(value=str(DEFAULT_DIR))
        self.launch_after = tk.BooleanVar(value=True)
        self.step = 0
        self._frames: list[tk.Frame] = []
        self._build_ui()
        self._show_step(0)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="#1e293b", height=72)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text="AI-AGENT 数字员工平台",
            fg="white",
            bg="#1e293b",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor=tk.W, padx=24, pady=(16, 0))
        tk.Label(
            header,
            text="本地安装 · 共用单位数据库 · 不含源码交付",
            fg="#94a3b8",
            bg="#1e293b",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor=tk.W, padx=24, pady=(4, 0))

        self.body = tk.Frame(self, padx=28, pady=20)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.welcome = self._page_welcome()
        self.location = self._page_location()
        self.confirm = self._page_confirm()
        self.progress = self._page_progress()
        self.done = self._page_done()
        self._frames = [self.welcome, self.location, self.confirm, self.progress, self.done]

        nav = tk.Frame(self, pady=12, padx=24)
        nav.pack(fill=tk.X, side=tk.BOTTOM)
        self.btn_back = tk.Button(nav, text="< 上一步", width=10, command=self._back)
        self.btn_back.pack(side=tk.LEFT)
        self.btn_next = tk.Button(nav, text="下一步 >", width=10, command=self._next, default=tk.ACTIVE)
        self.btn_next.pack(side=tk.RIGHT)
        self.btn_cancel = tk.Button(nav, text="取消", width=8, command=self.destroy)
        self.btn_cancel.pack(side=tk.RIGHT, padx=(0, 8))

    def _page_welcome(self) -> tk.Frame:
        f = tk.Frame(self.body)
        tk.Label(f, text="欢迎使用 AI-AGENT 安装向导", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        tk.Label(
            f,
            text=(
                "本向导将在您的电脑上安装 AI-AGENT（本地前端 + 后端）。\n\n"
                "• 安装后访问：http://localhost:3000\n"
                "• 业务数据连接单位数据库（已预配置）\n"
                "• 安装包已去除 .py / .tsx 源码，仅含运行文件\n\n"
                "点击「下一步」选择安装位置。"
            ),
            justify=tk.LEFT,
            font=("Microsoft YaHei UI", 10),
            wraplength=480,
        ).pack(anchor=tk.W, pady=(16, 0))
        return f

    def _page_location(self) -> tk.Frame:
        f = tk.Frame(self.body)
        tk.Label(f, text="选择安装位置", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        tk.Label(f, text="建议保留默认路径：", font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(16, 4))
        row = tk.Frame(f)
        row.pack(fill=tk.X, pady=4)
        tk.Entry(row, textvariable=self.install_dir, width=52).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(row, text="浏览…", command=self._browse).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(
            f,
            text="需要约 1.5 GB 磁盘空间。",
            fg="#64748b",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor=tk.W, pady=(12, 0))
        return f

    def _page_confirm(self) -> tk.Frame:
        f = tk.Frame(self.body)
        tk.Label(f, text="确认安装", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        self.confirm_text = tk.Label(
            f,
            text="",
            justify=tk.LEFT,
            font=("Microsoft YaHei UI", 10),
            wraplength=480,
        )
        self.confirm_text.pack(anchor=tk.W, pady=(16, 0))
        return f

    def _page_progress(self) -> tk.Frame:
        f = tk.Frame(self.body)
        tk.Label(f, text="正在安装…", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(f, length=460, mode="determinate")
        self.progress_bar.pack(pady=(24, 8))
        self.progress_label = tk.Label(f, text="准备中…", font=("Microsoft YaHei UI", 9))
        self.progress_label.pack(anchor=tk.W)
        return f

    def _page_done(self) -> tk.Frame:
        f = tk.Frame(self.body)
        tk.Label(f, text="安装完成！", font=("Microsoft YaHei UI", 12, "bold"), fg="#059669").pack(anchor=tk.W)
        tk.Label(
            f,
            text=f"AI-AGENT 已安装。\n浏览器访问：{HTTP_URL}",
            justify=tk.LEFT,
            font=("Microsoft YaHei UI", 10),
            wraplength=480,
        ).pack(anchor=tk.W, pady=(16, 8))
        tk.Checkbutton(f, text="立即启动 AI-AGENT", variable=self.launch_after).pack(anchor=tk.W)
        return f

    def _browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.install_dir.get())
        if path:
            self.install_dir.set(path)

    def _show_step(self, idx: int) -> None:
        self.step = idx
        for fr in self._frames:
            fr.pack_forget()
        self._frames[idx].pack(fill=tk.BOTH, expand=True)
        self.btn_back["state"] = tk.NORMAL if idx in (1, 2) else tk.DISABLED
        if idx == 0:
            self.btn_next["text"] = "下一步 >"
            self.btn_next["state"] = tk.NORMAL
            self.btn_cancel["state"] = tk.NORMAL
        elif idx == 1:
            self.btn_next["text"] = "下一步 >"
            self.btn_next["state"] = tk.NORMAL
        elif idx == 2:
            self._update_confirm()
            self.btn_next["text"] = "安装"
            self.btn_next["state"] = tk.NORMAL
        elif idx == 3:
            self.btn_back["state"] = tk.DISABLED
            self.btn_next["state"] = tk.DISABLED
            self.btn_cancel["state"] = tk.DISABLED
            threading.Thread(target=self._run_install, daemon=True).start()
        elif idx == 4:
            self.btn_back["state"] = tk.DISABLED
            self.btn_next["text"] = "完成"
            self.btn_next["state"] = tk.NORMAL
            self.btn_cancel["state"] = tk.DISABLED

    def _update_confirm(self) -> None:
        self.confirm_text["text"] = (
            f"安装到：\n  {self.install_dir.get()}\n\n"
            "将安装：前端 + 后端 + 运行环境（无源码）\n"
            "数据库：10.9.240.114:5432 / fian / schema aiagent\n\n"
            "点击「安装」开始。"
        )

    def _back(self) -> None:
        if self.step > 0:
            self._show_step(self.step - 1)

    def _next(self) -> None:
        if self.step == 4:
            if self.launch_after.get():
                self._start_app()
            self.destroy()
            return
        if self.step == 1:
            path = Path(self.install_dir.get().strip())
            if not path.drive:
                messagebox.showerror(APP_TITLE, "请选择有效的安装路径。")
                return
        if self.step == 2:
            self._show_step(3)
            return
        self._show_step(self.step + 1)

    def _run_install(self) -> None:
        try:
            archive = _find_zip()
            if archive is None:
                raise FileNotFoundError("安装包内找不到 AI-AGENT-package.zip")

            target = Path(self.install_dir.get().strip())
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

            tmp = Path(tempfile.mkdtemp(prefix="aiagnet-setup-"))
            try:
                app_root = target
                with zipfile.ZipFile(archive) as zf:
                    members = zf.infolist()
                    total = max(len(members), 1)
                    for i, member in enumerate(members, 1):
                        zf.extract(member, tmp)
                        pct = int(i * 50 / total)
                        self._set_progress(pct, f"解压文件… {member.filename[:40]}")

                children = list(tmp.iterdir())
                app_dir: Path | None = None
                if len(children) == 1 and children[0].is_dir():
                    app_dir = children[0]
                elif (tmp / "AI-AGENT.bat").is_file():
                    app_dir = tmp
                else:
                    for prefix in ("aiagnet-win-secure-", "aiagnet-win-"):
                        matched = [p for p in tmp.iterdir() if p.is_dir() and p.name.startswith(prefix)]
                        if len(matched) == 1:
                            app_dir = matched[0]
                            break
                if app_dir is None:
                    raise RuntimeError("安装包格式不正确")
                shutil.move(str(app_dir), str(app_root))

                bat = app_root / "AI-AGENT.bat"
                if not bat.is_file():
                    raise RuntimeError("安装不完整：缺少 AI-AGENT.bat")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            self._set_progress(100, "安装完成")
            self.after(300, lambda: self._show_step(4))
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror(APP_TITLE, f"安装失败：\n{exc}"))
            self.after(0, lambda: self._show_step(2))

    def _set_progress(self, value: int, text: str) -> None:
        def update() -> None:
            self.progress_bar["value"] = value
            self.progress_label["text"] = text
        self.after(0, update)

    def _start_app(self) -> None:
        root = Path(self.install_dir.get().strip())
        bat = root / "AI-AGENT.bat"
        if bat.is_file():
            subprocess.Popen(["cmd.exe", "/c", "start", "", str(bat)], cwd=str(root), shell=False)
            try:
                webbrowser.open(HTTP_URL)
            except OSError:
                pass


def main() -> None:
    app = Wizard()
    app.mainloop()


if __name__ == "__main__":
    main()
