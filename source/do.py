import os
import asyncio
from dotenv import load_dotenv
from source.main import selenium_task

# 1. Load environment variables first
load_dotenv('.env')

# 2. Get configuration from environment (or use the literal assignments 
#    if you prefer them, but remove the redundant ones)
#    We will use os.getenv() for robustness.
CHROME_DRIVER_PATH = r"H:\document\program\project\site access\chromedriver\chromedriver.exe"
USER_DATA_DIR = r"H:\document\program\project\site access\chrome_auto_profile"
PROFILE_NAME = "Default"
VITE_TARGETURL="https://bz-ticket.com/receptions/f709da29-64ac-4922-b633-8d17520ed7e2"
VITE_TARGETTIME="2025-11-23 03:11:00"
VITE_KEYWORDS="申込み"
VITE_CHROMEPATH=r"H:\document\program\project\site access\chromedriver\chromedriver.exe"
VITE_DATADIR=r"H:\document\program\project\site access\chrome_auto_profile"
VITE_PROFILENAME="Default"
VITE_WSURL="ws://127.0.0.1:8000/ws"
VITE_BLOCK_KEYWORDS="東京ドーム"
VITE_TICKET_QUANTITY=2
VITE_AUTO_PROCEED=True
VITE_SEAT_PREFERENCE="SS"
VITE_WAIT_FOR_RECAPTCHA=True
VITE_STOP_AFTER_FIRST_CLICK=True

# VITE_WSURL is not used in main, but kept for completeness
VITE_WSURL = os.getenv("VITE_WSURL")

# run_command() is removed as it was unused and redundant.

async def main():
    # 3. Create a task to run the blocking Selenium function in a separate thread.
    task = asyncio.create_task(asyncio.to_thread(
        selenium_task,
        VITE_TARGETURL, VITE_TARGETTIME, VITE_KEYWORDS, VITE_CHROMEPATH, 
        VITE_DATADIR, VITE_PROFILENAME,
        VITE_BLOCK_KEYWORDS,
        VITE_TICKET_QUANTITY, VITE_AUTO_PROCEED, VITE_SEAT_PREFERENCE, 
        VITE_WAIT_FOR_RECAPTCHA, VITE_STOP_AFTER_FIRST_CLICK
    ))
    
    print("status: started")
    
    # 4. Await the task to ensure the main event loop waits for its completion.
    #    Alternatively, if the selenium_task has a long runtime, use while True/asyncio.sleep
    await task 
    print("status: finished")

# 5. CRITICAL FIX: Correct the entry point check
if __name__ == "__main__":
    asyncio.run(main())