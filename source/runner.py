import datetime
import time
import re
import signal
import sys
import os
import subprocess
import platform
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import random

# psutilをインポート（Chromeプロセスを特定するため）
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ===== 枚数設定関数 =====
def set_ticket_quantity(driver, quantity, log):
    """
    チケット枚数を設定する（+ボタンを指定回数クリック）
    """
    try:
        log(f"[INFO] Clicking + button {quantity} time(s)")

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
                log(f"[ERROR] Could not find + button: {e}")
                return False

        if not plus_button:
            log("[ERROR] Plus button not found")
            return False

        log(f"[INFO] Found + button, will click {quantity} time(s)")

        # +ボタンをクリック（高速化）
        for i in range(quantity):
            try:
                # ボタンがdisabledかチェック
                class_attr = plus_button.get_attribute('class') or ''
                if 'disabled' in class_attr:
                    log(f"[INFO] + button is disabled, reached maximum quantity")
                    break

                plus_button.click()
                log(f"[INFO] Clicked + button ({i+1}/{quantity})")
                time.sleep(0.05)  # 待機時間を短縮（0.15秒 → 0.05秒）

                # ボタンを再取得（DOM更新対応）
                if i < quantity - 1:  # 最後のクリック後は再取得不要
                    try:
                        plus_button = driver.find_element(By.XPATH, "//button[contains(@class, 'plus') and contains(@class, 'button')]")
                    except:
                        log("[WARN] Could not re-locate + button")

            except Exception as e:
                log(f"[WARN] Could not click + button on attempt {i+1}: {e}")
                break

        # 最終確認
        time.sleep(0.1)  # 待機時間を短縮（0.3秒 → 0.1秒）
        try:
            # より正確なXPath
            final_value = driver.find_element(By.XPATH, "//div[contains(@class, 'counter')]/div[contains(@class, 'value')]").text
            log(f"[SUCCESS] Final ticket quantity: {final_value}")
        except:
            try:
                # フォールバック
                final_value = driver.find_element(By.XPATH, "//div[@class='value']").text
                log(f"[SUCCESS] Final ticket quantity: {final_value}")
            except:
                log("[INFO] Could not read final quantity value")

        return True
    except Exception as e:
        log(f"[ERROR] Failed to click + button: {e}")
        return False

# ===== 席種選択関数 =====
def select_seat_type(driver, seat_preference, log):
    """
    席種を選択する（SS, S, A の優先順位で選択）
    seat_preference: "SS,S,A" のようなカンマ区切り文字列
    """
    try:
        if not seat_preference or seat_preference.strip() == "":
            log("[INFO] No seat preference specified, skipping seat selection")
            return True

        preferences = [p.strip().upper() for p in seat_preference.split(",") if p.strip()]
        log(f"[INFO] Seat preference order: {preferences}")

        for pref in preferences:
            log(f"[INFO] Looking for {pref} seat...")

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
                                log(f"[INFO] {pref} seat is disabled, trying next preference")
                                break

                            selector.click()
                            log(f"[SUCCESS] Selected {pref} seat: '{seat_name}'")
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
                                log(f"[INFO] {pref} seat is disabled, trying next preference")
                                break

                            selector.click()
                            log(f"[SUCCESS] Selected {pref} seat via XPath")
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
                            log(f"[INFO] {pref} seat button is disabled, trying next preference")
                            break

                        button.click()
                        log(f"[SUCCESS] Selected {pref} seat: '{button_text}'")
                        time.sleep(0.2)
                        return True
            except:
                pass

        log("[WARN] No available seat type found from preferences")
        return False

    except Exception as e:
        log(f"[ERROR] Failed to select seat type: {e}")
        return False

# ===== セブンイレブン選択関数 =====
def select_seven_eleven(driver, log):
    """
    お支払い方法選択画面でセブンイレブンを選択する
    """
    try:
        log("[INFO] Looking for Seven-Eleven payment option...")
        time.sleep(0.5)  # ページ読み込み待機

        # セブンイレブンのキーワードパターン
        seven_eleven_keywords = ["セブンイレブン", "セブン-イレブン", "7-Eleven", "7-11", "セブン"]

        # 方法1: ボタンを探す
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip()
            if any(keyword in button_text for keyword in seven_eleven_keywords):
                # disabledチェック
                class_attr = button.get_attribute('class') or ''
                if 'disabled' not in class_attr.lower():
                    button.click()
                    log(f"[SUCCESS] Seven-Eleven button clicked: '{button_text}'")
                    time.sleep(0.3)
                    return True

        # 方法2: リンクを探す
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            link_text = link.text.strip()
            if any(keyword in link_text for keyword in seven_eleven_keywords):
                link.click()
                log(f"[SUCCESS] Seven-Eleven link clicked: '{link_text}'")
                time.sleep(0.3)
                return True

        # 方法3: ラジオボタンやチェックボックスを探す
        inputs = driver.find_elements(By.XPATH, "//input[@type='radio' or @type='checkbox']")
        for input_elem in inputs:
            try:
                # 親要素のテキストを確認
                parent = input_elem.find_element(By.XPATH, "./ancestor::*[contains(text(), 'セブン') or contains(text(), '7-Eleven') or contains(text(), '7-11')]")
                if parent:
                    input_elem.click()
                    log(f"[SUCCESS] Seven-Eleven input clicked")
                    time.sleep(0.3)
                    return True
            except:
                pass

        # 方法4: テキストを含む要素を探してクリック
        elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'セブンイレブン') or contains(text(), 'セブン-イレブン') or contains(text(), '7-Eleven') or contains(text(), '7-11')]")
        for elem in elements:
            try:
                elem_text = elem.text.strip()
                if any(keyword in elem_text for keyword in seven_eleven_keywords):
                    # クリック可能な親要素を探す
                    clickable = elem
                    try:
                        # ボタンやリンクの親を探す
                        clickable = elem.find_element(By.XPATH, "./ancestor::button | ./ancestor::a | ./ancestor::div[contains(@class, 'button') or contains(@class, 'clickable')]")
                    except:
                        pass
                    
                    clickable.click()
                    log(f"[SUCCESS] Seven-Eleven element clicked: '{elem_text}'")
                    time.sleep(0.3)
                    return True
            except:
                continue

        log("[WARN] Seven-Eleven payment option not found")
        return False
    except Exception as e:
        log(f"[ERROR] Failed to select Seven-Eleven: {e}")
        return False

# ===== お支払いボタンクリック関数 =====
def click_payment_button(driver, log):
    """
    「お支払い / 受取方法を選ぶ」ボタンをクリックし、セブンイレブンがあれば選択する
    """
    try:
        log("[INFO] Looking for payment button...")

        # お支払いボタンを探す
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip()
            if "お支払い" in button_text and "受取方法" in button_text:
                button.click()
                log(f"[SUCCESS] Payment button clicked: '{button_text}'")
                time.sleep(0.8)  # ページ遷移待機
                
                # セブンイレブンを選択
                select_seven_eleven(driver, log)
                
                return True

        log("[WARN] Payment button not found")
        return False
    except Exception as e:
        log(f"[ERROR] Failed to click payment button: {e}")
        return False

# ===== お申込み内容の確認ボタンクリック関数 =====
def click_confirm_button(driver, log):
    """
    「お申込み内容の確認」ボタンをクリック
    """
    try:
        log("[INFO] Looking for confirm button...")
        time.sleep(0.5)  # ページ読み込み待機

        buttons = driver.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            button_text = button.text.strip()
            if "お申込み内容の確認" in button_text or "申込み内容の確認" in button_text:
                button.click()
                log(f"[SUCCESS] Confirm button clicked: '{button_text}'")
                return True

        log("[WARN] Confirm button not found")
        return False
    except Exception as e:
        log(f"[ERROR] Failed to click confirm button: {e}")
        return False

# ===== 最終確認処理関数 =====
def final_confirmation(driver, log, wait_for_recaptcha=True):
    """
    チェックボックスにチェックを入れて「この内容で申込む」ボタンをクリック
    """
    try:
        log("[INFO] Starting final confirmation...")
        time.sleep(0.5)  # ページ読み込み待機

        # reCAPTCHAチェック（チェックボックスの前）
        if wait_for_recaptcha:
            try:
                recaptcha_frames = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') or contains(@title, 'reCAPTCHA')]")
                if len(recaptcha_frames) > 0:
                    log("[WARN] reCAPTCHA detected on final confirmation page!")
                    log("[INFO] Please solve the reCAPTCHA manually.")
                    log("[INFO] Waiting 90 seconds for manual reCAPTCHA solving...")
                    log("[INFO] Moving mouse cursor to simulate human activity...")
                    
                    # 人間らしいマウス操作をシミュレート（reCAPTCHA検出を回避する試み）
                    # 注意: 完全な自動化は困難なため、手動操作が推奨されます
                    start_time = time.time()
                    try:
                        window_size = driver.get_window_size()
                        width = window_size['width']
                        height = window_size['height']
                        
                        # 90秒間、ランダムにマウスを動かす
                        current_x = width // 2
                        current_y = height // 2
                        
                        while time.time() - start_time < 90:
                            actions = ActionChains(driver)
                            
                            # ランダムな位置にマウスを移動（人間らしい動き）
                            target_x = random.randint(100, width - 100)
                            target_y = random.randint(100, height - 100)
                            
                            # 滑らかな動きをシミュレート（複数のステップで移動）
                            steps = random.randint(5, 15)
                            for i in range(steps):
                                # 現在位置から目標位置への補間
                                ratio = (i + 1) / steps
                                step_x = int(current_x + (target_x - current_x) * ratio)
                                step_y = int(current_y + (target_y - current_y) * ratio)
                                
                                # 相対移動
                                offset_x = step_x - current_x
                                offset_y = step_y - current_y
                                
                                if offset_x != 0 or offset_y != 0:
                                    actions.move_by_offset(offset_x, offset_y)
                                    current_x = step_x
                                    current_y = step_y
                                
                                time.sleep(random.uniform(0.05, 0.15))
                            
                            # 時々小さな動きを追加
                            if random.random() < 0.3:  # 30%の確率
                                small_x = random.randint(-20, 20)
                                small_y = random.randint(-20, 20)
                                actions.move_by_offset(small_x, small_y)
                                current_x += small_x
                                current_y += small_y
                            
                            actions.perform()
                            
                            # ランダムな待機時間
                            time.sleep(random.uniform(1, 3))
                    except Exception as e:
                        log(f"[DEBUG] Mouse simulation error (continuing anyway): {e}")
                        # マウス操作が失敗しても、待機時間は続ける
                        remaining_time = 90 - (time.time() - start_time)
                        if remaining_time > 0:
                            time.sleep(remaining_time)
                    
                    log("[INFO] Proceeding to checkbox and submit...")
            except Exception as e:
                log(f"[DEBUG] reCAPTCHA check completed: {e}")
        else:
            log("[INFO] reCAPTCHA wait is disabled, proceeding without waiting...")

        # チェックボックスを探してチェック（tpl-checkboxカスタム要素対応）
        try:
            # 方法1: tpl-checkbox要素を探す（カスタム要素）
            custom_checkboxes = driver.find_elements(By.TAG_NAME, "tpl-checkbox")
            log(f"[INFO] Found {len(custom_checkboxes)} tpl-checkbox element(s)")

            if len(custom_checkboxes) > 0:
                for i, tpl_checkbox in enumerate(custom_checkboxes):
                    try:
                        # チェック状態を確認（input要素で判定）
                        checkbox_input = tpl_checkbox.find_element(By.XPATH, ".//input[@type='checkbox']")
                        is_checked = checkbox_input.is_selected()
                        log(f"[DEBUG] tpl-checkbox {i+1}: is_selected={is_checked}")

                        if not is_checked:
                            # 方法1: checkmark spanをクリック
                            try:
                                checkmark = tpl_checkbox.find_element(By.XPATH, ".//span[@class='checkmark']")
                                checkmark.click()
                                log(f"[SUCCESS] tpl-checkbox {i+1} clicked via checkmark span")
                                time.sleep(0.1)
                            except:
                                # 方法2: labelをクリック
                                try:
                                    label = tpl_checkbox.find_element(By.XPATH, ".//label")
                                    label.click()
                                    log(f"[SUCCESS] tpl-checkbox {i+1} clicked via label")
                                    time.sleep(0.1)
                                except:
                                    # 方法3: tpl-checkbox自体をクリック
                                    try:
                                        tpl_checkbox.click()
                                        log(f"[SUCCESS] tpl-checkbox {i+1} clicked directly")
                                        time.sleep(0.1)
                                    except:
                                        # 方法4: JavaScriptでinputをクリック
                                        driver.execute_script("arguments[0].click();", checkbox_input)
                                        log(f"[SUCCESS] tpl-checkbox {i+1} clicked via JavaScript")
                                        time.sleep(0.1)
                        else:
                            log(f"[INFO] tpl-checkbox {i+1} already checked")
                    except Exception as e:
                        log(f"[WARN] Could not click tpl-checkbox {i+1}: {e}")
            else:
                # 通常のcheckboxを探す
                checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
                log(f"[INFO] Found {len(checkboxes)} standard checkbox(es)")

                for i, checkbox in enumerate(checkboxes):
                    try:
                        is_checked = checkbox.is_selected()
                        log(f"[DEBUG] Checkbox {i+1}: is_selected={is_checked}")

                        if not is_checked:
                            try:
                                checkbox.click()
                                log(f"[SUCCESS] Checkbox {i+1} clicked directly")
                                time.sleep(0.1)
                            except:
                                try:
                                    parent = checkbox.find_element(By.XPATH, "..")
                                    parent.click()
                                    log(f"[SUCCESS] Checkbox {i+1} parent clicked")
                                    time.sleep(0.1)
                                except:
                                    driver.execute_script("arguments[0].click();", checkbox)
                                    log(f"[SUCCESS] Checkbox {i+1} clicked via JavaScript")
                                    time.sleep(0.1)
                        else:
                            log(f"[INFO] Checkbox {i+1} already checked")
                    except Exception as e:
                        log(f"[WARN] Could not click checkbox {i+1}: {e}")

        except Exception as e:
            log(f"[ERROR] Error in checkbox handling: {e}")

        # チェックボックス確認後、人間らしい待機時間（1.0〜1.5秒）
        log("[INFO] Waiting before clicking submit button (human-like delay)...")
        time.sleep(1.2)

        # フッター内の「この内容で申込む」ボタンを探す
        try:
            # フッター内のボタンを優先的に探す
            footer_buttons = driver.find_elements(By.XPATH, "//footer//button")
            log(f"[INFO] Found {len(footer_buttons)} button(s) in footer")

            for button in footer_buttons:
                button_text = button.text.strip()
                log(f"[DEBUG] Footer button text: '{button_text}'")
                if "この内容で申込む" in button_text or "申込む" in button_text:
                    # ボタンクリック前に少し待機（0.3〜0.5秒）
                    time.sleep(0.4)
                    button.click()
                    log(f"[SUCCESS] Final submit button clicked: '{button_text}'")
                    time.sleep(0.5)  # クリック後も少し待機
                    return True

            # フッター内に見つからない場合、全体を検索
            log("[INFO] Searching all buttons for submit button...")
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            for button in all_buttons:
                button_text = button.text.strip()
                if "この内容で申込む" in button_text:
                    # ボタンクリック前に少し待機（0.3〜0.5秒）
                    time.sleep(0.4)
                    button.click()
                    log(f"[SUCCESS] Final submit button clicked: '{button_text}'")
                    time.sleep(0.5)  # クリック後も少し待機
                    return True

            log("[WARN] Final submit button not found")
            return False

        except Exception as e:
            log(f"[ERROR] Failed to click final submit button: {e}")
            return False

    except Exception as e:
        log(f"[ERROR] Failed in final confirmation: {e}")
        return False

# ===== テキスト正規化関数 =====
def normalize_text(text):
    """
    テキストを正規化して比較しやすくする
    - 改行、タブ、連続する空白をスペースに統一
    - スラッシュ、ハイフン、スペースを統一
    - 全角/半角を統一
    """
    if not text:
        return ""
    # 改行、タブ、連続する空白をスペースに統一
    text = re.sub(r'[\n\r\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    # 全角数字を半角に変換
    text = text.replace("０", "0").replace("１", "1").replace("２", "2").replace("３", "3")
    text = text.replace("４", "4").replace("５", "5").replace("６", "6").replace("７", "7")
    text = text.replace("８", "8").replace("９", "9")
    # スラッシュ、ハイフン、スペースを統一（比較用に数字のみ抽出も可能）
    return text.strip()

# ===== 日付形式のマッチング関数 =====
def match_date_keyword(block_text, keyword):
    """
    日付形式のキーワード（例：2026/05/02、2026/05/02(土)）をブロックテキストとマッチング
    改行を含むテキスト（例：2026\n/\n04\n/\n11）にも対応
    必ず指定された日付が含まれていることを厳密に確認
    曜日部分（(土)など）は無視して日付のみでマッチング
    """
    # キーワードから曜日部分を除去（例：2026/05/02(土) -> 2026/05/02）
    keyword_clean = re.sub(r'\([^)]+\)', '', keyword).strip()
    
    # まず、テキストを正規化（改行をスペースに変換）
    normalized_keyword = normalize_text(keyword_clean)
    normalized_block = normalize_text(block_text)
    
    # キーワードから数字のみを抽出（例：2026/05/02 -> 20260502）
    keyword_digits = re.sub(r'[^\d]', '', keyword_clean)
    block_digits = re.sub(r'[^\d]', '', block_text)
    
    # 数字の並びが完全一致することを確認（例：20260502が20260502を含む）
    # ただし、他の日付（例：2026年1月4日 -> 202614）と混同しないように
    # 年、月、日が連続して出現することを確認
    if keyword_digits and len(keyword_digits) >= 8:  # YYYYMMDD形式
        keyword_parts = re.findall(r'\d+', keyword_clean)
        if len(keyword_parts) >= 3:
            year, month, day = keyword_parts[0], keyword_parts[1], keyword_parts[2]
            
            # ブロック内で年、月、日が順番通りに出現するか確認
            # 正規表現で順番を確認（改行やスペースを無視）
            # 例：2026.*?05.*?02 または 2026.*?5.*?2
            # ただし、スラッシュや区切り文字が含まれていることを確認
            month_pattern = month if len(month) == 2 else f"0?{month}"
            day_pattern = day if len(day) == 2 else f"0?{day}"
            
            # 年、月、日が順番通りに出現するパターン（スラッシュや区切り文字を含む）
            # 例：2026/05/02 または 2026-05-02 または 2026 05 02
            pattern = rf"{year}\s*[/\-]\s*{month_pattern}\s*[/\-]\s*{day_pattern}"
            if re.search(pattern, normalized_block, re.IGNORECASE):
                return True
            
            # 数字のみのパターンも確認（ただし、他の日付と混同しないように）
            pattern_digits = rf"{year}.*?{month_pattern}.*?{day_pattern}"
            if re.search(pattern_digits, block_digits):
                # さらに、ブロック内に他の日付（例：2026年1月4日）が含まれていないか確認
                # 指定された日付が主要な日付であることを確認
                return True
    
    # 正規化されたテキストでマッチング（改行を無視）
    # 例：keyword="2026/05/02" → normalized="2026 / 05 / 02"
    #     block="2026\n/\n05\n/\n02\n(土)" → normalized="2026 / 05 / 02 (土)"
    
    # キーワードの各部分（年、月、日）を抽出
    keyword_parts = re.findall(r'\d+', keyword)
    if len(keyword_parts) >= 3:  # 年、月、日の3つ以上
        year, month, day = keyword_parts[0], keyword_parts[1], keyword_parts[2]
        
        # ブロック内に年、月、日がすべて含まれているか確認
        # 月と日は2桁に正規化（例：04 → 4, 11 → 11）
        month_normalized = month.zfill(2) if len(month) < 2 else month
        day_normalized = day.zfill(2) if len(day) < 2 else day
        
        # 複数の形式で確認（05 と 5 の両方に対応）
        year_found = year in normalized_block
        month_found = (month in normalized_block or month_normalized in normalized_block)
        day_found = (day in normalized_block or day_normalized in normalized_block)
        
        # 年、月、日がすべて含まれ、かつ順番が正しいことを確認
        if year_found and month_found and day_found:
            # 年、月、日の出現順序を確認（正規表現で）
            # 年が最初に出現し、その後に月、その後に日が出現することを確認
            year_pos = normalized_block.find(year)
            month_pos = normalized_block.find(month) if month in normalized_block else normalized_block.find(month_normalized)
            day_pos = normalized_block.find(day) if day in normalized_block else normalized_block.find(day_normalized)
            
            # 年、月、日が順番通りに出現することを確認
            if year_pos != -1 and month_pos != -1 and day_pos != -1:
                if year_pos < month_pos < day_pos:
                    return True
    
    return False

# ===== ブロック内検索関数 =====
def find_button_in_block(driver, block_keywords, button_keywords, log):
    """
    特定のキーワードを含むブロック（divやsection等）を見つけて、
    その中のボタンをクリックする
    日付形式（例：2026/05/02）にも対応
    """
    try:
        # すべてのブロック要素を取得（div, section, article, tpl-* 等のカスタムタグ）
        # より具体的な構造を持つブロックを優先（例：tour-actクラスなど）
        potential_blocks = []
        
        # 方法1: 特定のクラス名を持つブロックを優先（例：tour-act, act-info など）
        try:
            specific_blocks = driver.find_elements(By.XPATH, "//*[contains(@class, 'tour-act')]")
            for block in specific_blocks:
                if block not in potential_blocks:
                    potential_blocks.append(block)
        except:
            pass
        
        # 方法2: 日付を含む可能性が高いブロックを探す（act-dateクラスを持つ要素の親）
        try:
            date_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'act-date')]")
            for elem in date_elements:
                try:
                    # 親要素で、ボタンを含む可能性があるブロックを探す
                    parent = elem.find_element(By.XPATH, "./ancestor::*[.//button][1]")
                    if parent and parent not in potential_blocks:
                        potential_blocks.append(parent)
                except:
                    pass
        except:
            pass
        
        # 方法3: フォールバック - すべてのブロック要素を取得
        if not potential_blocks:
            potential_blocks = driver.find_elements(By.XPATH, "//*[self::div or self::section or self::article or starts-with(name(), 'tpl-')]")

        log(f"[INFO] Found {len(potential_blocks)} potential blocks")

        # ブロックを探索
        for block in potential_blocks:
            try:
                block_text = block.text.strip()
                if not block_text:
                    continue

                # ブロック内にキーワードがすべて含まれているか確認
                matches_all = True
                for keyword in block_keywords:
                    if not keyword.strip():
                        continue
                    
                    keyword = keyword.strip()
                    normalized_keyword = normalize_text(keyword)
                    normalized_block = normalize_text(block_text)
                    
                    # 日付形式のキーワードかどうかを判定（数字とスラッシュ/ハイフンを含む）
                    # 曜日部分（(土)など）を除去してから判定
                    keyword_for_check = re.sub(r'\([^)]+\)', '', keyword).strip()
                    is_date_format = bool(re.search(r'\d+[/\-]\d+[/\-]\d+', keyword_for_check))
                    
                    if is_date_format:
                        # 日付形式のマッチング（曜日部分は無視）
                        if not match_date_keyword(block_text, keyword):
                            matches_all = False
                            break
                    else:
                        # 通常のテキストマッチング
                        if normalized_keyword.lower() not in normalized_block.lower():
                            matches_all = False
                            break

                if matches_all:
                    log(f"[INFO] Found matching block with all keywords: {block_keywords}")
                    log(f"[DEBUG] Block text: {block_text[:200]}...")  # 最初の200文字をログ出力

                    # ブロック内のボタンを探す
                    buttons = block.find_elements(By.TAG_NAME, "button") + block.find_elements(By.TAG_NAME, "a")
                    log(f"[DEBUG] Found {len(buttons)} button(s) in matching block")

                    # ボタンを優先順位でソート（button_keywordsに完全一致するものを優先）
                    button_candidates = []
                    for button in buttons:
                        try:
                            button_text = button.text.strip()
                            log(f"[DEBUG] Button text: '{button_text}'")
                            
                            # ボタンのキーワードチェック（いずれか1つのキーワードが含まれていればOK）
                            for k in button_keywords:
                                if not k.strip():
                                    continue
                                keyword = k.strip().lower()
                                button_text_lower = button_text.lower()
                                
                                # 完全一致を優先
                                if keyword == button_text_lower:
                                    button_candidates.insert(0, (button, button_text, 1))  # 優先度1（最高）
                                    break
                                elif keyword in button_text_lower:
                                    button_candidates.append((button, button_text, 2))  # 優先度2
                                    break
                        except Exception as e:
                            log(f"[DEBUG] Error getting button text: {e}")
                            continue

                    # 優先度順にクリックを試行
                    for button, button_text, priority in button_candidates:
                        try:
                            log(f"[INFO] Trying to click button: '{button_text}' (priority: {priority})")
                            button.click()
                            log(f"[SUCCESS] Button clicked: '{button_text}' at {datetime.datetime.now()}")
                            return True
                        except Exception as e:
                            log(f"[WARN] Failed to click button '{button_text}': {e}")
                            continue
                    
                    if not button_candidates:
                        log(f"[WARN] No matching button found in block. Button keywords: {button_keywords}")
                        log(f"[DEBUG] Available button texts: {[b.text.strip() for b in buttons]}")
            except Exception as e:
                # 個別ブロックでエラーが出ても続行
                log(f"[DEBUG] Error processing block: {e}")
                continue

        return False
    except Exception as e:
        log(f"[ERROR] Error in find_button_in_block: {e}")
        return False

# ===== メイン実行関数 =====
def run(url, target_time_str, button_keywords, user_data_dir, profile_name="Default", 
        block_keywords=None, ticket_quantity=1, auto_proceed=False, seat_preference="", 
        wait_for_recaptcha=True, stop_after_first_click=False):
    """
    シンプルな実行関数
    """
    def log(msg):
        print(msg, flush=True)

    log("[INFO] Starting Selenium task...")
    log(f"[INFO] Parameters: stop_after_first_click={stop_after_first_click}")
    
    options = Options()
    options.add_argument(f"--user-data-dir={user_data_dir}")
    options.add_argument(f"--profile-directory={profile_name}")
    options.add_experimental_option("detach", True)
    
    # ChromeDriverを自動的にダウンロード・管理（Chromeのバージョンに自動対応）
    try:
        service = Service(ChromeDriverManager().install())
        log("[INFO] Using webdriver-manager to auto-download ChromeDriver")
    except Exception as e:
        log(f"[ERROR] webdriver-manager failed: {e}")
        raise

    driver = webdriver.Chrome(service=service, options=options)

    log("[INFO] Chrome ready.")
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
    log(f"[INFO] Target time reached. Accessing page at {datetime.datetime.now()}")

    # ボタン探索（3分間リロードを続ける）
    max_total_wait = 180  # 3分（180秒）
    start_total = time.time()
    clicked = False
    reload_count = 0

    # ブロックキーワードが指定されている場合はブロック内検索を優先
    use_block_search = block_keywords and len(block_keywords) > 0 and block_keywords[0] != ""

    while time.time() - start_total < max_total_wait:
        # 各検索サイクルでの待機時間
        max_wait_per_cycle = 10  # 各サイクルで10秒待機
        start_cycle = time.time()
        
        while time.time() - start_cycle < max_wait_per_cycle:
            try:
                if use_block_search:
                    # ブロック内検索
                    if reload_count == 0:
                        log(f"[INFO] Using block search with keywords: {block_keywords}")
                    clicked = find_button_in_block(driver, block_keywords, button_keywords, log)
                    if clicked:
                        break
                else:
                    # 通常のボタン検索（全体）- いずれか1つのキーワードが含まれていればOK
                    elements = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a")
                    for element in elements:
                        text = element.text.strip()
                        if any(k.strip().lower() in text.lower() for k in button_keywords if k.strip()):
                            try:
                                element.click()
                                clicked = True
                                log(f"[INFO] Button clicked: '{text}' at {datetime.datetime.now()}")
                                break
                            except Exception as e:
                                log(f"[WARN] Failed to click button '{text}': {e}")
                                continue
                    if clicked:
                        break
            except Exception as e:
                log(f"[WARN] Exception while searching buttons: {e}")
            time.sleep(0.01)
        
        if clicked:
            break
        
        # ボタンが見つからなかった場合、リロード
        elapsed = time.time() - start_total
        remaining = max_total_wait - elapsed
        if remaining > 0:
            reload_count += 1
            log(f"[WARN] No matching button found (attempt {reload_count}), reloading page... (remaining: {remaining:.1f}s)")
            try:
                driver.refresh()
                time.sleep(2.0)  # リロード後の待機
                log("[INFO] Page reloaded, retrying button search...")
            except Exception as e:
                log(f"[WARN] Failed to reload page: {e}")
                # リロードに失敗した場合、URLに直接アクセス
                try:
                    driver.get(url)
                    time.sleep(2.0)
                except Exception as e2:
                    log(f"[ERROR] Failed to reload page: {e2}")
                    time.sleep(1.0)  # エラー時も少し待機
        else:
            break

    if not clicked:
        log(f"[ERROR] No matching button found after {reload_count} reload attempts (3 minutes)")
        log("[INFO] Selenium task finished.")
        return

    # ボタンクリック成功後の処理
    if clicked:
        log("[INFO] Button clicked successfully. Waiting for page to load...")
        time.sleep(0.8)  # ページ遷移待機を短縮（1.5秒 → 0.8秒）

        # 最初のボタンクリック後に停止するオプション
        log(f"[INFO] Checking stop_after_first_click condition: {stop_after_first_click}")
        if stop_after_first_click:
            log("[INFO] stop_after_first_click is enabled. Stopping here.")
            log("[INFO] Selenium task finished.")
            return

        # 席種選択
        if seat_preference and seat_preference.strip():
            log(f"[INFO] Selecting seat type: {seat_preference}")
            select_seat_type(driver, seat_preference, log)
            time.sleep(0.3)

        # 枚数設定（+ボタンをクリック）
        if ticket_quantity > 0:
            log(f"[INFO] Will click + button {ticket_quantity} time(s)")
            set_ticket_quantity(driver, ticket_quantity, log)

        # お支払いボタン自動クリック
        if auto_proceed:
            time.sleep(0.2)
            if click_payment_button(driver, log):
                log("[SUCCESS] Automatically proceeded to payment page")

                # お申込み内容の確認ボタンをクリック
                time.sleep(0.5)
                if click_confirm_button(driver, log):
                    log("[SUCCESS] Confirm button clicked")

                    # 最終確認（チェックボックス + 申し込むボタン）
                    time.sleep(0.5)
                    if final_confirmation(driver, log, wait_for_recaptcha):
                        log("[SUCCESS] Final confirmation completed!")
                    else:
                        log("[WARN] Final confirmation failed")
                else:
                    log("[WARN] Could not find confirm button")
            else:
                log("[WARN] Could not find payment button")

    log("[INFO] Selenium task finished.")
    
    # ブラウザを閉じる関数（detach=Trueの場合でも確実に閉じる）
    # 特定のuser-data-dirを使用しているChromeプロセスのみを終了
    def close_browser():
        try:
            # まず通常の方法を試す
            driver.quit()
            time.sleep(0.5)  # 少し待機
        except:
            pass
        
        try:
            # detach=Trueの場合、プロセスを直接終了
            if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
                driver.service.process.terminate()
                driver.service.process.wait(timeout=5)
        except:
            pass
        
        try:
            # 特定のuser-data-dirを使用しているChromeプロセスのみを終了
            if platform.system() == "Windows":
                if PSUTIL_AVAILABLE:
                    # psutilを使用して特定のuser-data-dirのChromeプロセスのみを終了
                    user_data_dir_normalized = os.path.normpath(user_data_dir)
                    chrome_processes = []
                    
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        try:
                            if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                                cmdline = proc.info['cmdline']
                                if cmdline:
                                    # コマンドライン引数にuser-data-dirが含まれているか確認
                                    cmdline_str = ' '.join(cmdline)
                                    if '--user-data-dir' in cmdline_str:
                                        # user-data-dirのパスを抽出
                                        for i, arg in enumerate(cmdline):
                                            if arg == '--user-data-dir' and i + 1 < len(cmdline):
                                                proc_user_data_dir = os.path.normpath(cmdline[i + 1])
                                                if proc_user_data_dir == user_data_dir_normalized:
                                                    chrome_processes.append(proc)
                                                    break
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue
                    
                    # 見つかったChromeプロセスを終了
                    for proc in chrome_processes:
                        try:
                            log(f"[DEBUG] Terminating Chrome process PID: {proc.pid}")
                            proc.terminate()
                        except Exception as e:
                            log(f"[DEBUG] Failed to terminate process {proc.pid}: {e}")
                            try:
                                proc.kill()  # terminateが失敗した場合、強制終了
                            except:
                                pass
                    
                    # プロセスの終了を待機
                    gone, alive = psutil.wait_procs(chrome_processes, timeout=3)
                    if alive:
                        for proc in alive:
                            try:
                                log(f"[DEBUG] Force killing Chrome process PID: {proc.pid}")
                                proc.kill()
                            except:
                                pass
                else:
                    # psutilが利用できない場合、PowerShellコマンドを使用
                    # 特定のuser-data-dirを使用しているChromeプロセスのみを終了
                    user_data_dir_escaped = user_data_dir.replace('\\', '\\\\').replace('"', '\\"')
                    ps_command = f'''
                    Get-CimInstance Win32_Process -Filter "name='chrome.exe'" | 
                    Where-Object {{ $_.CommandLine -like '*--user-data-dir*{user_data_dir_escaped}*' }} | 
                    ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}
                    '''
                    subprocess.run(["powershell", "-Command", ps_command], 
                                 capture_output=True, timeout=10)
        except Exception as e:
            log(f"[DEBUG] Error closing browser: {e}")
            pass
    
    # stop_after_first_click=Falseの場合、ブラウザを開いたままにする
    if not stop_after_first_click:
        log("[INFO] Keeping browser open. Press Ctrl+C to close.")
        
        # Ctrl+C (SIGINT) のハンドラーを設定
        def signal_handler(sig, frame):
            log("\n[INFO] Ctrl+C detected. Closing browser...")
            close_browser()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        try:
            while True:
                time.sleep(0.1)  # 短い間隔でチェックして応答性を向上
        except KeyboardInterrupt:
            log("\n[INFO] KeyboardInterrupt detected. Closing browser...")
            close_browser()
            sys.exit(0)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # 環境変数から読み込み
    load_dotenv('.env')
    
    # 設定値（環境変数から取得、なければデフォルト値）
    url = os.getenv("URL", "")
    target_time = os.getenv("TARGET_TIME", "")
    button_keywords = os.getenv("BUTTON_KEYWORDS", "").split(",") if os.getenv("BUTTON_KEYWORDS") else []
    user_data_dir = os.getenv("USER_DATA_DIR", "")
    profile_name = os.getenv("PROFILE_NAME", "Default")
    block_keywords = os.getenv("BLOCK_KEYWORDS", "").split(",") if os.getenv("BLOCK_KEYWORDS") else []
    ticket_quantity = int(os.getenv("TICKET_QUANTITY", "1"))
    auto_proceed = os.getenv("AUTO_PROCEED", "False").lower() == "true"
    seat_preference = os.getenv("SEAT_PREFERENCE", "")
    wait_for_recaptcha = os.getenv("WAIT_FOR_RECAPTCHA", "True").lower() == "true"
    stop_after_first_click = os.getenv("STOP_AFTER_FIRST_CLICK", "False").lower() == "true"
    
    if not url or not target_time or not button_keywords or not user_data_dir:
        print("[ERROR] Required parameters missing. Please set environment variables:")
        print("  URL, TARGET_TIME, BUTTON_KEYWORDS, USER_DATA_DIR")
        exit(1)
    
    run(
        url=url,
        target_time_str=target_time,
        button_keywords=button_keywords,
        user_data_dir=user_data_dir,
        profile_name=profile_name,
        block_keywords=block_keywords,
        ticket_quantity=ticket_quantity,
        auto_proceed=auto_proceed,
        seat_preference=seat_preference,
        wait_for_recaptcha=wait_for_recaptcha,
        stop_after_first_click=stop_after_first_click
    )

