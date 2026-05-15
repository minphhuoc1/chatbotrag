# -*- coding: utf-8 -*-
"""Browser-level UI smoke test via Edge/Chrome DevTools Protocol.

This intentionally avoids Playwright/Selenium packages. It launches Microsoft
Edge with a temporary profile, clicks the real UI, types text via CDP Input,
and verifies that the chat DOM updates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import requests
import websocket


ROOT = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
URL = "http://127.0.0.1:3007"
DEBUG_PORT = 9223
PROFILE_DIR = ROOT / "tmp" / "edge-cdp-profile"


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=10)
        self.next_id = 1

    def call(self, method: str, params: dict | None = None) -> dict:
        msg_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv()
            payload = json.loads(raw)
            if payload.get("id") == msg_id:
                if "error" in payload:
                    raise RuntimeError(f"{method} failed: {payload['error']}")
                return payload.get("result", {})

    def eval(self, expression: str, await_promise: bool = False):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        remote = result.get("result", {})
        if "value" in remote:
            return remote["value"]
        return None

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def wait_for(condition, timeout: float = 20.0, interval: float = 0.25, label: str = "condition"):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        last = condition()
        if last:
            return last
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {label}; last={last!r}")


def get_ws_url() -> str:
    endpoint = f"http://127.0.0.1:{DEBUG_PORT}/json"
    tabs = wait_for(
        lambda: requests.get(endpoint, timeout=2).json(),
        timeout=15,
        label="CDP /json endpoint",
    )
    for tab in tabs:
        if tab.get("type") == "page" and URL in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]
    for tab in tabs:
        if tab.get("type") == "page":
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError(f"No page target found: {tabs!r}")


def rect_for(cdp: CDP, selector_expr: str) -> dict:
    rect = cdp.eval(
        f"""
        (() => {{
          const el = {selector_expr};
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {{ x: r.x, y: r.y, width: r.width, height: r.height }};
        }})()
        """
    )
    if not rect:
        raise RuntimeError(f"Element not found for expression: {selector_expr}")
    return rect


def click_center(cdp: CDP, rect: dict):
    x = rect["x"] + rect["width"] / 2
    y = rect["y"] + rect["height"] / 2
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def body_text(cdp: CDP) -> str:
    return cdp.eval("document.body.innerText") or ""


def run() -> dict:
    if not EDGE.exists():
        raise FileNotFoundError(f"Microsoft Edge not found: {EDGE}")

    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [
            str(EDGE),
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--headless=new",
            "--window-size=1920,1080",
            "--remote-allow-origins=*",
            URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    cdp: CDP | None = None
    try:
        cdp = CDP(get_ws_url())
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False},
        )

        wait_for(lambda: cdp.eval("document.readyState") == "complete", label="document complete")
        wait_for(lambda: cdp.eval("!!document.querySelector('textarea')"), label="textarea")
        wait_for(lambda: cdp.eval("window.__LEXBOT_READY__ === true"), label="React hydration")
        wait_for(
            lambda: cdp.eval("""[...document.querySelectorAll('button')].some(b => b.innerText.includes('Gửi'))"""),
            label="send button",
        )

        manual_query = "Công ty nợ lương 2 tháng, tôi nghỉ ngay được không?"
        click_center(cdp, rect_for(cdp, "document.querySelector('textarea')"))
        cdp.call("Input.insertText", {"text": manual_query})
        wait_for(
            lambda: cdp.eval("document.querySelector('textarea')?.value") == manual_query,
            label="manual text entered",
        )
        click_center(
            cdp,
            rect_for(cdp, """[...document.querySelectorAll('button')].find(b => b.innerText.includes('Gửi'))"""),
        )
        wait_for(lambda: "Đang phân loại câu hỏi" in body_text(cdp), timeout=5, label="loading state")
        wait_for(lambda: "Căn cứ pháp lý" in body_text(cdp) and "Điều 35" in body_text(cdp), timeout=90, label="manual answer")

        sample_prompt = "Đơn phương chấm dứt hợp đồng trái luật thì phải bồi thường gì?"
        click_center(
            cdp,
            rect_for(cdp, f"""[...document.querySelectorAll('button')].find(b => b.innerText.includes('Đơn phương chấm dứt'))"""),
        )
        wait_for(lambda: sample_prompt in body_text(cdp), timeout=10, label="sample prompt rendered")
        wait_for(lambda: body_text(cdp).count("Căn cứ pháp lý") >= 1, timeout=90, label="sample answer")

        text = body_text(cdp)
        return {
            "ok": True,
            "manual_query_visible": manual_query in text,
            "manual_article_35_visible": "Điều 35" in text,
            "sample_prompt_visible": sample_prompt in text,
            "send_button_visible": "Gửi" in text,
        }
    finally:
        if cdp is not None:
            cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
