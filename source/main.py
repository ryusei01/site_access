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
    print(f"[WebSocket] New connection attempt from {websocket.client}")
    await websocket.accept()
    print(f"[WebSocket] Connection accepted")
    connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        print(f"[WebSocket] Connection disconnected")
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
    block_keywords: str = Form(""),  # ブロック検索用キーワード（オプション）
    ticket_quantity: int = Form(1),  # チケット枚数（デフォルト1枚）
    auto_proceed: bool = Form(False),  # お支払いボタン自動クリック
    seat_preference: str = Form(""),  # 席種の優先順位（例: "SS,S,A"）
    wait_for_recaptcha: bool = Form(True),  # reCAPTCHA検出時に待機するか
    stop_after_first_click: bool = Form(False),  # 最初のボタンクリック後に停止
):
    log_queue.put(f"[INFO] Run called with URL: {url}")
    log_queue.put(f"[INFO] Parameters received in /run endpoint:")
    log_queue.put(f"[INFO]   auto_proceed={auto_proceed} (type: {type(auto_proceed).__name__})")
    log_queue.put(f"[INFO]   wait_for_recaptcha={wait_for_recaptcha} (type: {type(wait_for_recaptcha).__name__})")
    log_queue.put(f"[INFO]   stop_after_first_click={stop_after_first_click} (type: {type(stop_after_first_click).__name__})")
    asyncio.create_task(asyncio.to_thread(
        selenium_task,
        url, target_time, button_keywords.split(","), chrome_path, user_data_dir, profile_name,
        block_keywords.split(",") if block_keywords else [],
        ticket_quantity, auto_proceed, seat_preference, wait_for_recaptcha, stop_after_first_click
    ))
    return {"status": "started"}

# ===== 枚数設定関数 =====
def set_ticket_quantity(driver, quantity, ws_log):
    """
    チケット枚数を設定する（+ボタンを指定回数クリック）
    """
    try:
        ws_log(f"[INFO] Clicking + button {quantity} time(s)")

        # +ボタンを探す（複数の方法を試す）
        plus_button = None
        try:
            # 方法1: XPathでclass名を含むボタンを探す
            plus_button = driver.find_element(By.XPATH, "//button[contains(@class, 'plus') and contains(@class, 'button')]")
        except:
            try:
                # 方法2: XPathでカウンター内のボタンを探す
                buttons = driver.find_elements(By.XPATH, "//div[contains(@class, 'counter')]//button")
                for btn in buttons:
                    if 'plus' in btn.get_attribute('class'):
                        plus_button = btn
                        break
            except Exception as e:
                ws_log(f"[ERROR] Could not find + button: {e}")
                return False

        if not plus_button:
            ws_log("[ERROR] Plus button not found")
            return False

        ws_log(f"[INFO] Found + button, will click {quantity} time(s)")

        # +ボタンをクリック（高速化）
        for i in range(quantity):
            try:
                # ボタンがdisabledかチェック
                class_attr = plus_button.get_attribute('class') or ''
                if 'disabled' in class_attr:
                    ws_log(f"[INFO] + button is disabled, reached maximum quantity")
                    break

                plus_button.click()
                ws_log(f"[INFO] Clicked + button ({i+1}/{quantity})")
                time.sleep(0.05)  # 待機時間を短縮（0.15秒 → 0.05秒）

                # ボタンを再取得（DOM更新対応）
                if i < quantity - 1:  # 最後のクリック後は再取得不要
                    try:
                        plus_button = driver.find_element(By.XPATH, "//button[contains(@class, 'plus') and contains(@class, 'button')]")
                    except:
                        ws_log("[WARN] Could not re-locate + button")

            except Exception as e:
                ws_log(f"[WARN] Could not click + button on attempt {i+1}: {e}")
                break

        # 最終確認
        time.sleep(0.1)  # 待機時間を短縮（0.3秒 → 0.1秒）
        try:
            # より正確なXPath
            final_value = driver.find_element(By.XPATH, "//div[contains(@class, 'counter')]/div[contains(@class, 'value')]").text
            ws_log(f"[SUCCESS] Final ticket quantity: {final_value}")
        except:
            try:
                # フォールバック
                final_value = driver.find_element(By.XPATH, "//div[@class='value']").text
                ws_log(f"[SUCCESS] Final ticket quantity: {final_value}")
            except:
                ws_log("[INFO] Could not read final quantity value")

        return True
    except Exception as e:
        ws_log(f"[ERROR] Failed to click + button: {e}")
        return False

# ===== 席種選択関数 =====
def select_seat_type(driver, seat_preference, ws_log):
    """
    席種を選択する（SS, S, A の優先順位で選択）
    seat_preference: "SS,S,A" のようなカンマ区切り文字列
    """
    try:
        if not seat_preference or seat_preference.strip() == "":
            ws_log("[INFO] No seat preference specified, skipping seat selection")
            return True

        preferences = [p.strip().upper() for p in seat_preference.split(",") if p.strip()]
        ws_log(f"[INFO] Seat preference order: {preferences}")

        for pref in preferences:
            ws_log(f"[INFO] Looking for {pref} seat...")

            # 方法1: tpl-seat-info内のseat-nameを探す（新しいパターン）
            try:
                seat_infos = driver.find_elements(By.TAG_NAME, "tpl-seat-info")
                for seat_info in seat_infos:
                    try:
                        seat_name_elem = seat_info.find_element(By.XPATH, ".//div[contains(@class, 'seat-name')]")
                        seat_name = seat_name_elem.text.strip()

                        pref_lower = pref.lower()
                        seat_name_lower = seat_name.lower()

                        match = False
                        if f"{pref}席" == seat_name or pref == seat_name.replace("席", ""):
                            match = True
                        elif pref_lower == "premium" and ("premium" in seat_name_lower or "プレミアム" in seat_name):
                            match = True

                        if match:
                            # 親の selector 要素をクリック
                            selector = seat_info.find_element(By.XPATH, "./ancestor::div[contains(@class, 'selector')]")

                            # disabledチェック
                            class_attr = selector.get_attribute('class') or ''
                            if 'disabled' in class_attr.lower():
                                ws_log(f"[INFO] {pref} seat is disabled, trying next preference")
                                break

                            selector.click()
                            ws_log(f"[SUCCESS] Selected {pref} seat: '{seat_name}'")
                            time.sleep(0.2)
                            return True
                    except:
                        continue
            except:
                pass

            # 方法2: XPathで席名テキストを含むdiv要素を探す（フォールバック）
            try:
                # 席名を含むテキストを持つ要素を探す
                seat_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{pref}席')]")
                for elem in seat_elements:
                    try:
                        elem_text = elem.text.strip()

                        # 完全一致または部分一致チェック
                        if f"{pref}席" == elem_text or f"{pref}席" in elem_text:
                            # 親のselector要素を探す
                            try:
                                selector = elem.find_element(By.XPATH, "./ancestor::div[contains(@class, 'selector')]")
                            except:
                                # selectorがない場合、クリック可能な親要素を探す
                                selector = elem.find_element(By.XPATH, "./ancestor::*[contains(@class, 'seat') or contains(@class, 'ticket')]")

                            # disabledチェック
                            class_attr = selector.get_attribute('class') or ''
                            if 'disabled' in class_attr.lower():
                                ws_log(f"[INFO] {pref} seat is disabled, trying next preference")
                                break

                            selector.click()
                            ws_log(f"[SUCCESS] Selected {pref} seat via XPath")
                            time.sleep(0.2)
                            return True
                    except:
                        continue
            except:
                pass

            # 方法3: ボタンを探す（最終フォールバック）
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for button in buttons:
                    button_text = button.text.strip()
                    pref_lower = pref.lower()
                    button_text_lower = button_text.lower()

                    match = False
                    if f"{pref}席" in button_text or button_text == pref:
                        match = True
                    elif pref_lower == "premium" and ("premium" in button_text_lower or "プレミアム" in button_text):
                        match = True

                    if match:
                        # ボタンがdisabledでないか確認
                        class_attr = button.get_attribute('class') or ''
                        if 'disabled' in class_attr.lower():
                            ws_log(f"[INFO] {pref} seat button is disabled, trying next preference")
                            break

                        button.click()
                        ws_log(f"[SUCCESS] Selected {pref} seat: '{button_text}'")
                        time.sleep(0.2)
                        return True
            except:
                pass

        ws_log("[WARN] No available seat type found from preferences")
        return False

    except Exception as e:
        ws_log(f"[ERROR] Failed to select seat type: {e}")
        return False

# ===== お支払いボタンクリック関数 =====
def click_payment_button(driver, ws_log):
    """
    「お支払い / 受取方法を選ぶ」ボタンをクリック
    """
    try:
        ws_log("[INFO] Looking for payment button...")

        # お支払いボタンを探す
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip()
            if "お支払い" in button_text and "受取方法" in button_text:
                button.click()
                ws_log(f"[SUCCESS] Payment button clicked: '{button_text}'")
                return True

        ws_log("[WARN] Payment button not found")
        return False
    except Exception as e:
        ws_log(f"[ERROR] Failed to click payment button: {e}")
        return False

# ===== お申込み内容の確認ボタンクリック関数 =====
def click_confirm_button(driver, ws_log):
    """
    「お申込み内容の確認」ボタンをクリック
    """
    try:
        ws_log("[INFO] Looking for confirm button...")
        time.sleep(0.5)  # ページ読み込み待機

        buttons = driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip()
            if "お申込み内容の確認" in button_text or "申込み内容の確認" in button_text:
                button.click()
                ws_log(f"[SUCCESS] Confirm button clicked: '{button_text}'")
                return True

        ws_log("[WARN] Confirm button not found")
        return False
    except Exception as e:
        ws_log(f"[ERROR] Failed to click confirm button: {e}")
        return False

# ===== 最終確認処理関数 =====
def final_confirmation(driver, ws_log, wait_for_recaptcha=True):
    """
    チェックボックスにチェックを入れて「この内容で申し込む」ボタンをクリック
    """
    try:
        ws_log("[INFO] Starting final confirmation...")
        time.sleep(0.5)  # ページ読み込み待機

        # reCAPTCHAチェック（チェックボックスの前）
        if wait_for_recaptcha:
            try:
                recaptcha_frames = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') or contains(@title, 'reCAPTCHA')]")
                if len(recaptcha_frames) > 0:
                    ws_log("[WARN] reCAPTCHA detected on final confirmation page!")
                    ws_log("[INFO] Please solve the reCAPTCHA manually.")
                    ws_log("[INFO] Waiting 90 seconds for manual reCAPTCHA solving...")
                    time.sleep(90)  # ユーザーが手動で解決する時間を与える
                    ws_log("[INFO] Proceeding to checkbox and submit...")
            except Exception as e:
                ws_log(f"[DEBUG] reCAPTCHA check completed: {e}")
        else:
            ws_log("[INFO] reCAPTCHA wait is disabled, proceeding without waiting...")

        # チェックボックスを探してチェック（tpl-checkboxカスタム要素対応）
        try:
            # 方法1: tpl-checkbox要素を探す（カスタム要素）
            custom_checkboxes = driver.find_elements(By.TAG_NAME, "tpl-checkbox")
            ws_log(f"[INFO] Found {len(custom_checkboxes)} tpl-checkbox element(s)")

            if len(custom_checkboxes) > 0:
                for i, tpl_checkbox in enumerate(custom_checkboxes):
                    try:
                        # チェック状態を確認（input要素で判定）
                        checkbox_input = tpl_checkbox.find_element(By.XPATH, ".//input[@type='checkbox']")
                        is_checked = checkbox_input.is_selected()
                        ws_log(f"[DEBUG] tpl-checkbox {i+1}: is_selected={is_checked}")

                        if not is_checked:
                            # 方法1: checkmark spanをクリック
                            try:
                                checkmark = tpl_checkbox.find_element(By.XPATH, ".//span[@class='checkmark']")
                                checkmark.click()
                                ws_log(f"[SUCCESS] tpl-checkbox {i+1} clicked via checkmark span")
                                time.sleep(0.1)
                            except:
                                # 方法2: labelをクリック
                                try:
                                    label = tpl_checkbox.find_element(By.XPATH, ".//label")
                                    label.click()
                                    ws_log(f"[SUCCESS] tpl-checkbox {i+1} clicked via label")
                                    time.sleep(0.1)
                                except:
                                    # 方法3: tpl-checkbox自体をクリック
                                    try:
                                        tpl_checkbox.click()
                                        ws_log(f"[SUCCESS] tpl-checkbox {i+1} clicked directly")
                                        time.sleep(0.1)
                                    except:
                                        # 方法4: JavaScriptでinputをクリック
                                        driver.execute_script("arguments[0].click();", checkbox_input)
                                        ws_log(f"[SUCCESS] tpl-checkbox {i+1} clicked via JavaScript")
                                        time.sleep(0.1)
                        else:
                            ws_log(f"[INFO] tpl-checkbox {i+1} already checked")
                    except Exception as e:
                        ws_log(f"[WARN] Could not click tpl-checkbox {i+1}: {e}")
            else:
                # 通常のcheckboxを探す
                checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
                ws_log(f"[INFO] Found {len(checkboxes)} standard checkbox(es)")

                for i, checkbox in enumerate(checkboxes):
                    try:
                        is_checked = checkbox.is_selected()
                        ws_log(f"[DEBUG] Checkbox {i+1}: is_selected={is_checked}")

                        if not is_checked:
                            try:
                                checkbox.click()
                                ws_log(f"[SUCCESS] Checkbox {i+1} clicked directly")
                                time.sleep(0.1)
                            except:
                                try:
                                    parent = checkbox.find_element(By.XPATH, "..")
                                    parent.click()
                                    ws_log(f"[SUCCESS] Checkbox {i+1} parent clicked")
                                    time.sleep(0.1)
                                except:
                                    driver.execute_script("arguments[0].click();", checkbox)
                                    ws_log(f"[SUCCESS] Checkbox {i+1} clicked via JavaScript")
                                    time.sleep(0.1)
                        else:
                            ws_log(f"[INFO] Checkbox {i+1} already checked")
                    except Exception as e:
                        ws_log(f"[WARN] Could not click checkbox {i+1}: {e}")

        except Exception as e:
            ws_log(f"[ERROR] Error in checkbox handling: {e}")

        # チェックボックス確認後、人間らしい待機時間（1.0〜1.5秒）
        ws_log("[INFO] Waiting before clicking submit button (human-like delay)...")
        time.sleep(1.2)

        # フッター内の「この内容で申し込む」ボタンを探す
        try:
            # フッター内のボタンを優先的に探す
            footer_buttons = driver.find_elements(By.XPATH, "//footer//button")
            ws_log(f"[INFO] Found {len(footer_buttons)} button(s) in footer")

            for button in footer_buttons:
                button_text = button.text.strip()
                ws_log(f"[DEBUG] Footer button text: '{button_text}'")
                if "この内容で申し込む" in button_text or "申し込む" in button_text:
                    # ボタンクリック前に少し待機（0.3〜0.5秒）
                    time.sleep(0.4)
                    button.click()
                    ws_log(f"[SUCCESS] Final submit button clicked: '{button_text}'")
                    time.sleep(0.5)  # クリック後も少し待機
                    return True

            # フッター内に見つからない場合、全体を検索
            ws_log("[INFO] Searching all buttons for submit button...")
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            for button in all_buttons:
                button_text = button.text.strip()
                if "この内容で申し込む" in button_text:
                    # ボタンクリック前に少し待機（0.3〜0.5秒）
                    time.sleep(0.4)
                    button.click()
                    ws_log(f"[SUCCESS] Final submit button clicked: '{button_text}'")
                    time.sleep(0.5)  # クリック後も少し待機
                    return True

            ws_log("[WARN] Final submit button not found")
            return False

        except Exception as e:
            ws_log(f"[ERROR] Failed to click final submit button: {e}")
            return False

    except Exception as e:
        ws_log(f"[ERROR] Failed in final confirmation: {e}")
        return False

# ===== ブロック内検索関数 =====
def find_button_in_block(driver, block_keywords, button_keywords, ws_log):
    """
    特定のキーワードを含むブロック（divやsection等）を見つけて、
    その中のボタンをクリックする
    """
    try:
        # すべてのブロック要素を取得（div, section, article, tpl-* 等のカスタムタグ）
        potential_blocks = driver.find_elements(By.XPATH, "//*[self::div or self::section or self::article or starts-with(name(), 'tpl-')]")

        ws_log(f"[INFO] Found {len(potential_blocks)} potential blocks")

        # ブロックを探索
        for block in potential_blocks:
            try:
                block_text = block.text.strip()

                # ブロック内にキーワードがすべて含まれているか確認（完全一致）
                if all(keyword.strip().lower() in block_text.lower() for keyword in block_keywords if keyword.strip()):
                    ws_log(f"[INFO] Found matching block with all keywords: {block_keywords}")

                    # ブロック内のボタンを探す
                    buttons = block.find_elements(By.TAG_NAME, "button") + block.find_elements(By.TAG_NAME, "a")

                    for button in buttons:
                        button_text = button.text.strip()

                        # ボタンのキーワードチェック（いずれか1つのキーワードが含まれていればOK）
                        if any(k.strip().lower() in button_text.lower() for k in button_keywords if k.strip()):
                            ws_log(f"[INFO] Found matching button: '{button_text}'")
                            button.click()
                            ws_log(f"[SUCCESS] Button clicked: '{button_text}' at {datetime.datetime.now()}")
                            return True
            except Exception as e:
                # 個別ブロックでエラーが出ても続行
                continue

        return False
    except Exception as e:
        ws_log(f"[ERROR] Error in find_button_in_block: {e}")
        return False

# ===== Seleniumタスク =====
def selenium_task(url, target_time_str, button_keywords, chrome_path, user_data_dir, profile_name, block_keywords=None, ticket_quantity=1, auto_proceed=False, seat_preference="", wait_for_recaptcha=True, stop_after_first_click=False):
    def ws_log(msg):
        log_queue.put(msg)

    ws_log("[INFO] Starting Selenium task...")
    ws_log(f"[INFO] selenium_task received stop_after_first_click={stop_after_first_click} (type: {type(stop_after_first_click).__name__})")
    options = Options()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_name}")
    options.add_experimental_option("detach", True)
    service = Service(chrome_path)
    driver = webdriver.Chrome(service=service, options=options)

    ws_log("[INFO] Chrome ready.")
    driver.get(url)
    time.sleep(0.5)

    # ターゲット時間待機（高精度）
    target_time = datetime.datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S")

    while True:
        now = datetime.datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining <= 0:
            break

        # 残り時間に応じて短いスリープで待機
        sleep_time = min(0.01, max(remaining, 0.001))  # 1ms〜10ms
        time.sleep(sleep_time)

    # 時間になったらアクセス
    driver.get(url)
    ws_log(f"[INFO] Target time reached. Accessing page at {datetime.datetime.now()}")

    # ボタン探索（高速クリック）
    max_wait = 10
    start = time.time()
    clicked = False

    # ブロックキーワードが指定されている場合はブロック内検索を優先
    use_block_search = block_keywords and len(block_keywords) > 0 and block_keywords[0] != ""

    while time.time() - start < max_wait:
        try:
            if use_block_search:
                # ブロック内検索
                ws_log(f"[INFO] Using block search with keywords: {block_keywords}")
                clicked = find_button_in_block(driver, block_keywords, button_keywords, ws_log)
                if clicked:
                    break
            else:
                # 通常のボタン検索（全体）- いずれか1つのキーワードが含まれていればOK
                elements = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a")
                for element in elements:
                    text = element.text.strip()
                    if any(k.strip().lower() in text.lower() for k in button_keywords if k.strip()):
                        element.click()
                        clicked = True
                        ws_log(f"[INFO] Button clicked: '{text}' at {datetime.datetime.now()}")
                        break
                if clicked:
                    break
        except Exception as e:
            ws_log(f"[WARN] Exception while searching buttons: {e}")
        time.sleep(0.01)

    if not clicked:
        ws_log("[WARN] No matching button found, reloading page...")
        driver.refresh()
        time.sleep(2.0)  # リロード後の待機
        ws_log("[INFO] Page reloaded, retrying button search...")

        # リロード後に再度検索
        max_wait_retry = 10
        start_retry = time.time()
        while time.time() - start_retry < max_wait_retry:
            try:
                if use_block_search:
                    # ブロック内検索
                    clicked = find_button_in_block(driver, block_keywords, button_keywords, ws_log)
                    if clicked:
                        ws_log(f"[SUCCESS] Button found and clicked after reload")
                        break
                else:
                    # 通常のボタン検索
                    elements = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a")
                    for element in elements:
                        text = element.text.strip()
                        if any(k.strip().lower() in text.lower() for k in button_keywords if k.strip()):
                            element.click()
                            clicked = True
                            ws_log(f"[SUCCESS] Button clicked after reload: '{text}'")
                            break
                    if clicked:
                        break
            except Exception as e:
                ws_log(f"[WARN] Exception while searching buttons after reload: {e}")
            time.sleep(0.01)

        if not clicked:
            ws_log("[ERROR] No matching button found even after reload")
            ws_log("[INFO] Selenium task finished.")
            return

    # ボタンクリック成功後の処理
    if clicked:
        ws_log("[INFO] Button clicked successfully. Waiting for page to load...")
        time.sleep(0.8)  # ページ遷移待機を短縮（1.5秒 → 0.8秒）

        # 最初のボタンクリック後に停止するオプション
        ws_log(f"[INFO] Checking stop_after_first_click condition: {stop_after_first_click} (type: {type(stop_after_first_click).__name__})")
        if stop_after_first_click:
            ws_log("[INFO] stop_after_first_click is enabled. Stopping here.")
            ws_log("[INFO] Selenium task finished.")
            return

        # 席種選択
        if seat_preference and seat_preference.strip():
            ws_log(f"[INFO] Selecting seat type: {seat_preference}")
            select_seat_type(driver, seat_preference, ws_log)
            time.sleep(0.3)

        # 枚数設定（+ボタンをクリック）
        if ticket_quantity > 0:
            ws_log(f"[INFO] Will click + button {ticket_quantity} time(s)")
            set_ticket_quantity(driver, ticket_quantity, ws_log)

        # お支払いボタン自動クリック
        if auto_proceed:
            time.sleep(0.2)
            if click_payment_button(driver, ws_log):
                ws_log("[SUCCESS] Automatically proceeded to payment page")

                # お申込み内容の確認ボタンをクリック
                time.sleep(0.5)
                if click_confirm_button(driver, ws_log):
                    ws_log("[SUCCESS] Confirm button clicked")

                    # 最終確認（チェックボックス + 申し込むボタン）
                    time.sleep(0.5)
                    if final_confirmation(driver, ws_log, wait_for_recaptcha):
                        ws_log("[SUCCESS] Final confirmation completed!")
                    else:
                        ws_log("[WARN] Final confirmation failed")
                else:
                    ws_log("[WARN] Could not find confirm button")
            else:
                ws_log("[WARN] Could not find payment button")

    ws_log("[INFO] Selenium task finished.")

# ===== WebSocket送信用タスク開始 =====
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(websocket_log_sender())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
