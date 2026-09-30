"""
WerticMods — десктоп-приложение.
Открывает фронтенд (GitHub Pages или локальный docs/index.html) в окне.
Рядом поднимает локальный API-сервер (server.py).
"""
import os, sys, json, time, threading
import webview
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---- читаем конфиг ----
with open(os.path.join(ROOT, "config.json"), "r", encoding="utf-8") as f:
    CFG = json.load(f)

GH_URL    = (CFG.get("github_pages_url") or "").strip()
HOST      = CFG.get("server_host", "127.0.0.1")
PORT      = int(CFG.get("server_port", 5000))
LOCAL_UI  = "file://" + os.path.join(ROOT, "docs", "index.html")

def start_server():
    sys.path.insert(0, ROOT)
    from server import app
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

def wait_server(timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            requests.get(f"http://{HOST}:{PORT}/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False

def main():
    # 1. Бэкенд
    threading.Thread(target=start_server, daemon=True).start()
    ok = wait_server()
    if not ok:
        print("⚠ Не удалось поднять API-сервер")

    # 2. Что открывать
    if GH_URL:
        url = GH_URL
        print(f"→ Открываю GitHub Pages: {url}")
    else:
        url = LOCAL_UI
        print(f"→ GitHub Pages не настроен, открываю локально: {url}")

    # 3. Окно как браузер
    webview.create_window(
        "WerticMods",
        url,
        width=1280, height=800, min_size=(900, 600),
        background_color="#0b0d13",
        text_select=True,
    )
    webview.start()

if __name__ == "__main__":
    main()