"""Ứng dụng FastAPI: API + phục vụ giao diện đã build."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..batch import store
from ..config import PROJECT_ROOT
from .api import router

UI_DIST = PROJECT_ROOT / "ui" / "dist"

_NO_UI_PAGE = """<!doctype html>
<html lang="vi"><meta charset="utf-8">
<title>VSF Data — chưa build giao diện</title>
<style>
 body{background:#111217;color:#d8d9da;font:15px/1.6 ui-sans-serif,system-ui,sans-serif;
      display:grid;place-items:center;min-height:100vh;margin:0}
 main{max-width:34rem;padding:2rem;background:#181b1f;border:1px solid #2e3038;border-radius:6px}
 code{background:#0b0c0e;padding:.15rem .4rem;border-radius:3px;color:#6e9fff}
 h1{font-size:1.15rem;margin:0 0 .75rem}
 a{color:#6e9fff}
</style>
<main>
 <h1>Chưa build giao diện</h1>
 <p>API đã chạy — xem <a href="/docs">/docs</a>. Để có giao diện:</p>
 <p><code>cd ui &amp;&amp; npm install &amp;&amp; npm run build</code></p>
 <p>Lúc phát triển thì chạy <code>npm run dev</code>, Vite sẽ tự chuyển tiếp
 <code>/api</code> sang máy chủ này.</p>
</main>
</html>"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="VSF Data",
        description="Giao diện quản lý cho tool gán nhãn & tăng cường dữ liệu POI",
        version="2.0.0",
    )
    store.init()
    app.include_router(router)

    if UI_DIST.is_dir():
        assets = UI_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            """Mọi đường dẫn không phải API đều trả index.html.

            Giao diện định tuyến phía client, nên tải thẳng /triage hay /jobs/12
            (hoặc bấm F5 ở đó) phải ra đúng ứng dụng chứ không phải 404.
            """
            candidate = UI_DIST / path
            if path and candidate.is_file() and candidate.is_relative_to(UI_DIST):
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def placeholder() -> HTMLResponse:
            return HTMLResponse(_NO_UI_PAGE)

    return app


app = create_app()


def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run(
        "vsf.server.app:app" if reload else app,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
