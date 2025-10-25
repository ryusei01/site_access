import subprocess
import threading
import time
import socket
import webbrowser
import tkinter as tk
from tkinter import scrolledtext, messagebox
import atexit
import os
import signal
import psutil

FRONTEND_DIR = r"H:\document\program\project\site access\source\frontend"
BACKEND_DIR = r"H:\document\program\project\site access\source"
REACT_PORT = 5173
FASTAPI_PORT = 8000

react_proc = None
fastapi_proc = None

root = tk.Tk()
root.title("Launcher")
root.geometry("600x400")

log_area = scrolledtext.ScrolledText(root, state='disabled')
log_area.pack(expand=True, fill='both', padx=10, pady=10)

# ===== ログ出力 =====
def log(msg, color="black"):
    log_area.configure(state='normal')
    log_area.insert(tk.END, msg + "\n", color)
    log_area.tag_config(color, foreground=color)
    log_area.see(tk.END)
    log_area.configure(state='disabled')

# ===== ポート待機 =====
def wait_for_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False

# ===== プロセスログ読み取り =====
def read_output(proc, color="black"):
    for line in proc.stdout:
        line = line.strip()
        if "ready" in line.lower() or "listening" in line.lower():
            log(line, "green")
        elif "error" in line.lower():
            log(line, "red")
        else:
            log(line, color)

# ===== React 起動 =====
def start_react():
    global react_proc
    log("Starting React (Vite)...", color="blue")
    react_proc = subprocess.Popen(
        [r"C:\Program Files\nodejs\npm.cmd", "run", "dev", "--", "--host"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )
    threading.Thread(target=read_output, args=(react_proc,), daemon=True).start()

# ===== FastAPI 起動 =====
def start_fastapi():
    global fastapi_proc
    log("Starting FastAPI...", color="blue")
    fastapi_proc = subprocess.Popen(
        ["uvicorn", "main:app", "--reload"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )
    threading.Thread(target=read_output, args=(fastapi_proc,), daemon=True).start()

# ===== ブラウザ起動 =====
def open_browser_when_ready():
    log(f"Waiting for React dev server on port {REACT_PORT}...", color="purple")
    if wait_for_port("localhost", REACT_PORT, timeout=30):
        time.sleep(0.5)
        webbrowser.open(f"http://localhost:{REACT_PORT}/")
        log(f"Browser opened: http://localhost:{REACT_PORT}/", color="green")
    else:
        log("React dev server did not start in time.", color="red")
        messagebox.showerror("Error", "React dev server did not start in time.")

# ===== プロセス終了 =====
def kill_process_by_port(port):
    """指定ポートを使っているプロセスをすべて終了、Launcher 自身は除外"""
    my_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.pid == my_pid:
            continue
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    log(f"Killing {proc.info['name']} (PID={proc.info['pid']}) on port {port}", "red")
                    proc.kill()
        except Exception:
            pass

def shutdown_existing_services():
    kill_process_by_port(FASTAPI_PORT)
    kill_process_by_port(REACT_PORT)

def cleanup():
    global react_proc, fastapi_proc
    for proc in [react_proc, fastapi_proc]:
        if proc and proc.poll() is None:
            try:
                log(f"Terminating process {proc.pid}...", "red")
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                os.kill(proc.pid, signal.SIGKILL)
                log(f"Force killed process {proc.pid}", "red")

# ===== Run ボタン =====
def run_all():
    log("Shutting down existing services...", "red")
    shutdown_existing_services()  # GUI は閉じない
    time.sleep(1)  # 念のため少し待つ

    # FastAPI 起動
    threading.Thread(target=start_fastapi, daemon=True).start()
    if wait_for_port("127.0.0.1", FASTAPI_PORT, timeout=20):
        # React 起動
        threading.Thread(target=start_react, daemon=True).start()
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    else:
        log("FastAPI did not start in time.", color="red")

# ===== Exit ボタン =====
def stop_all():
    cleanup()
    root.destroy()

# ===== atexit 登録 =====
atexit.register(cleanup)

# ===== Ctrl+C も捕まえる =====
def handle_sigint(sig, frame):
    log("SIGINT received, cleaning up...", "red")
    cleanup()
    exit(0)
signal.signal(signal.SIGINT, handle_sigint)

# ===== GUI =====
tk.Button(root, text="Run", command=run_all, width=20).pack(pady=5)
tk.Button(root, text="Exit", command=stop_all, width=20).pack(pady=5)
root.protocol("WM_DELETE_WINDOW", stop_all)
root.mainloop()
