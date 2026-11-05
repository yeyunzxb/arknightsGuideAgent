"""跨平台一键启动：首次安装依赖，之后使用文件指纹跳过安装。"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command, cwd=ROOT):
    subprocess.run([str(c) for c in command], cwd=cwd, check=True)


def fingerprint(paths):
    return hashlib.sha256(b"".join(p.read_bytes() for p in paths if p.exists())).hexdigest()


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"端口 {port} 已被占用，请先关闭之前的服务。")


def ready(url, processes):
    for _ in range(120):
        if any(p.poll() is not None for p in processes):
            raise RuntimeError("服务启动失败，请查看上方日志。")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.5)
    raise RuntimeError(f"等待服务超时：{url}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("请安装 Python 3.11 或更新版本。")
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        raise RuntimeError("请先安装 Node.js 18.19+（推荐 Node.js 22 LTS），然后重新打开终端。")
    RUNTIME.mkdir(exist_ok=True)
    if not PYTHON.exists():
        print("[1/3] 创建项目虚拟环境…", flush=True)
        run([sys.executable, "-m", "venv", VENV])
    requirements = ROOT / "backend/requirements.txt"
    backend_hash = fingerprint([requirements])
    backend_marker = RUNTIME / "backend.sha256"
    if not backend_marker.exists() or backend_marker.read_text() != backend_hash:
        print("[1/3] 安装后端依赖（首次启动需要网络）…", flush=True)
        run([PYTHON, "-m", "pip", "install", "-r", requirements])
        backend_marker.write_text(backend_hash)
    frontend = ROOT / "frontend"
    frontend_marker = RUNTIME / "frontend.sha256"
    frontend_paths = [frontend / "package.json", frontend / "package-lock.json"]
    frontend_hash = fingerprint(frontend_paths)
    if not (frontend / "node_modules").exists() or not frontend_marker.exists() or frontend_marker.read_text() != frontend_hash:
        print("[2/3] 安装前端依赖…", flush=True)
        run([npm, "ci" if (frontend / "package-lock.json").exists() else "install", "--no-audit", "--no-fund"], frontend)
        frontend_marker.write_text(fingerprint(frontend_paths))
    if args.install_only:
        print("依赖已就绪。")
        return
    free_port(8000)
    free_port(5173)
    print("[3/3] 启动 PRTS… 按 Ctrl+C 同时关闭前后端。", flush=True)
    processes = []
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        processes.append(subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT / "backend", **options))
        processes.append(subprocess.Popen([npm, "run", "dev"], cwd=frontend, **options))
        ready("http://127.0.0.1:8000/api/health", processes)
        ready("http://127.0.0.1:5173", processes)
        print("\nPRTS 已就绪：http://127.0.0.1:5173\nAPI 文档：http://127.0.0.1:8000/docs", flush=True)
        if not args.no_browser:
            webbrowser.open("http://127.0.0.1:5173")
        while all(p.poll() is None for p in processes):
            time.sleep(.5)
        raise RuntimeError("一个服务已退出，正在关闭另一个服务。")
    except KeyboardInterrupt:
        print("\n正在关闭 PRTS…")
    finally:
        for process in reversed(processes):
            if process.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\n启动失败：{error}", file=sys.stderr)
        sys.exit(1)
