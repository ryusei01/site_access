import datetime
import time
import asyncio
from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import queue
import threading

app = FastAPI()

# HTTP 用 CORS（fetch 等）
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket接続リスト
connections = []

# 非同期キュー
log_queue = queue.Queue()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        connections.remove(websocket)

# バックグラウンドでキューからWebSocketに送信
async def websocket_log_sender():
    while True:
        msg = await asyncio.to_thread(log_queue.get)
        for ws in connections:
            try:
                await ws.send_text(msg)
            except:
                pass

# ===== 実行API =====
@app.post("/run")
async def run_script(
    url: str = Form(...),
    target_time: str = Form(...),
    button_keywords: str = Form(...),
    chrome_path: str = Form(...),
    user_data_dir: str = Form(...),
    profile_name: str = Form("Default"),
):
    log_queue.put(f"[INFO] Run called with URL: {url}")
    asyncio.create_task(asyncio.to_thread(
        selenium_task,
        url, target_time, button_keywords.split(","), chrome_path, user_data_dir, profile_name
    ))
    return {"status": "started"}

# ===== Seleniumタスク =====
def selenium_task(url, target_time_str, button_keywords, chrome_path, user_data_dir, profile_name):
    def ws_log(msg):
        log_queue.put(msg)

    ws_log("[INFO] Starting Selenium task...")
    options = Options()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_name}")
    options.add_experimental_option("detach", True)
    service = Service(chrome_path)
    driver = webdriver.Chrome(service=service, options=options)

    ws_log("[INFO] Chrome ready.")
    driver.get(url)
    time.sleep(0.5)

    # ターゲット時間待機
    target_time = datetime.datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S")
    now = datetime.datetime.now()
    remaining = (target_time - now).total_seconds()
    if remaining <= 0:
        ws_log("[INFO] Target time already passed. Executing immediately.")
    else:
        ws_log(f"[INFO] Waiting for target time: {target_time} ({remaining:.3f}s left)")
        while remaining > 0:
            time.sleep(min(remaining, 0.5))
            now = datetime.datetime.now()
            remaining = (target_time - now).total_seconds()

    ws_log("[INFO] Target time reached. Accessing page...")
    driver.get(url)

    # ボタン探索（高速）
    ws_log("[INFO] Searching for the button...")
    max_wait = 10
    start = time.time()
    clicked = False
    while time.time() - start < max_wait:
        try:
            elements = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a")
            for element in elements:
                text = element.text.strip()
                if any(k.lower() in text.lower() for k in button_keywords):
                    element.click()
                    clicked = True
                    now = datetime.datetime.now()
                    log_queue.put(f"[INFO] Button clicked: '{text}', {now}")
                    break
            if clicked:
                break
        except:
            pass
        time.sleep(0.01)

    if not clicked:
        ws_log("[WARN] No matching button found.")

    ws_log("[INFO] Selenium task finished.")
    # ===== WebSocket送信用タスク開始 =====
    asyncio.create_task(websocket_log_sender())

