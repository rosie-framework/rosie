"""HTTP + WebSocket server for ``rosie viz``."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from rosie.tools.viz.bridge import VizBridge

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(bridge: VizBridge) -> Any:
    try:
        from starlette.applications import Starlette
        from starlette.responses import FileResponse
        from starlette.routing import Mount, Route, WebSocketRoute
        from starlette.staticfiles import StaticFiles
        from starlette.websockets import WebSocket, WebSocketDisconnect
    except ImportError as e:
        raise ImportError(
            "rosie viz requires starlette and uvicorn (installed with Rosie core).\n"
            '  pip install "rosie-framework"'
        ) from e

    clients: set[WebSocket] = set()
    clients_lock = asyncio.Lock()

    async def index(_request: Any) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        async with clients_lock:
            clients.add(websocket)
        try:
            await websocket.send_text(json.dumps(bridge.snapshot()))
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "select":
                    robot = msg.get("robot")
                    bridge.select_robot(str(robot) if robot else None)
                elif mtype == "bag_cmd":
                    bridge.bag_cmd(
                        str(msg.get("cmd", "")),
                        t=msg.get("t"),
                        rate=msg.get("rate"),
                    )
        except WebSocketDisconnect:
            pass
        finally:
            async with clients_lock:
                clients.discard(websocket)

    async def broadcaster() -> None:
        while True:
            await asyncio.sleep(0.05)
            payload = json.dumps(bridge.snapshot())
            async with clients_lock:
                dead: list[WebSocket] = []
                for ws in clients:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    clients.discard(ws)

    async def on_startup() -> None:
        asyncio.create_task(broadcaster())

    return Starlette(
        routes=[
            Route("/", index),
            WebSocketRoute("/ws", ws_endpoint),
            Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
        ],
        on_startup=[on_startup],
    )


def run_server(
    bridge: VizBridge,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    try:
        import uvicorn
    except ImportError as e:
        raise ImportError(
            "rosie viz requires starlette and uvicorn (installed with Rosie core).\n"
            '  pip install "rosie-framework"'
        ) from e

    app = create_app(bridge)
    url = f"http://{host}:{port}/"
    print(f"Rosie viz → {url}")
    if open_browser:
        threading.Thread(
            target=lambda: (time.sleep(0.4), webbrowser.open(url)),
            daemon=True,
        ).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
