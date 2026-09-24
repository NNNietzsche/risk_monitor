import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .portal import Portal, NewsCreate, AISettings, NewsOut, AIStatus, DashboardOut, SeedOut, TimelinePage
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .responses import (RegionOut, MonitorOut, MonitorDetail, EventPage, EventDetail, PollResult, BatchPollResult, HealthOut, SourceOut)
from .models import MonitorCreate, MonitorPatch, PollRequest, RegionCreate, RuleChange, BusinessProfile, utc
from .store import Store, NotFound, Conflict
from .management import update_profile, remove_monitor, restore_monitor, change_region_deleted


ROOT = Path(__file__).resolve().parent.parent


def create_app(db_path=None, interval=None):
    store = Store(db_path or os.getenv("RISK_DB_PATH", str(ROOT / "data" / "risk.db")))
    portal = Portal(store)
    seconds = int(os.getenv("RISK_POLL_SECONDS", "3600")) if interval is None else interval
    if seconds != 0 and seconds < 5:
        raise ValueError("RISK_POLL_SECONDS 必须为 0（关闭）或 >= 5")

    async def scheduler():
        while True:
            await asyncio.sleep(seconds)
            try:
                await asyncio.to_thread(store.poll_all)
            except Exception:
                logging.exception("Monitoring cycle failed")

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduler()) if seconds else None
        async def ai_scheduler():
            while True:
                await asyncio.sleep(60)
                try:
                    await asyncio.to_thread(portal.refresh, True)
                except Conflict:
                    pass
                except Exception:
                    logging.error("Optional AI cycle failed")
        ai_task = asyncio.create_task(ai_scheduler())
        yield
        ai_task.cancel()
        with suppress(asyncio.CancelledError):
            await ai_task
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="资产风险监控 API", version="0.1.0", lifespan=lifespan,
                  description="公开 AIS / ADS-B 与 Mock Provider；确定性规则与可追溯事件。")
    app.state.store = store
    app.state.portal = portal
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin_boundary(request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PATCH", "DELETE", "PUT"} and origin and origin not in {"http://127.0.0.1:3000", "http://localhost:3000", "http://127.0.0.1:8000", "http://localhost:8000"}:
            return JSONResponse(status_code=403, content={"detail": "不接受其他网站发起的修改请求"})
        return await call_next(request)

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/api/v1/health", response_model=HealthOut)
    def health():
        modes = {not m["source"]["is_mock"] for m in store.monitors() if m["enabled"]}
        return {"status": "ok", "mode": "mixed" if len(modes)>1 else "live" if modes == {True} else "mock", "scheduler_seconds": seconds, "engine_version": "1.0.0"}

    @app.get("/api/v1/public/targets")
    def public_targets():
        return store.registry.discover()

    @app.get("/api/v1/public/sources", response_model=dict[str, SourceOut])
    def public_sources():
        return store.registry.catalog()

    @app.get("/api/v1/regions", response_model=list[RegionOut])
    def regions(include_deleted: bool = False):
        return store.regions(include_deleted)

    @app.post("/api/v1/regions", status_code=201, response_model=RegionOut)
    def create_region(body: RegionCreate):
        return store.create_region(body)

    @app.get("/api/v1/monitors", response_model=list[MonitorOut])
    def monitors(include_deleted: bool = False):
        return store.monitors(include_deleted)

    @app.post("/api/v1/monitors", status_code=201, response_model=MonitorDetail)
    def create_monitor(body: MonitorCreate):
        return store.create_monitor(body)

    @app.delete("/api/v1/regions/{region_id}")
    def delete_region(region_id: str):
        return change_region_deleted(store,region_id,True)

    @app.post("/api/v1/regions/{region_id}/restore")
    def restore_region(region_id: str):
        return change_region_deleted(store,region_id,False)

    @app.delete("/api/v1/monitors/{monitor_id}")
    def delete_monitor(monitor_id: str):
        return remove_monitor(store,monitor_id)

    @app.post("/api/v1/monitors/{monitor_id}/restore", response_model=MonitorDetail)
    def undo_delete_monitor(monitor_id: str):
        return restore_monitor(store,monitor_id)

    @app.patch("/api/v1/monitors/{monitor_id}/profile", response_model=MonitorDetail)
    def edit_profile(monitor_id: str, body: BusinessProfile):
        return update_profile(store,monitor_id,body)

    @app.get("/api/v1/monitors/{monitor_id}", response_model=MonitorDetail)
    def detail(monitor_id: str):
        return store.detail(monitor_id)

    @app.patch("/api/v1/monitors/{monitor_id}", response_model=MonitorDetail)
    def update_monitor(monitor_id: str, body: MonitorPatch):
        return store.set_enabled(monitor_id, body.enabled)

    @app.post("/api/v1/monitors/{monitor_id}/rule-versions", status_code=201, response_model=MonitorDetail)
    def change_rule(monitor_id: str, body: RuleChange):
        return store.change_rule(monitor_id, body)

    @app.post("/api/v1/monitors/{monitor_id}/poll", response_model=PollResult)
    def poll(monitor_id: str, body: PollRequest):
        return store.poll(monitor_id, body.scenario.value)

    @app.post("/api/v1/poll", response_model=BatchPollResult)
    def poll_all(group: Literal["vessel","aviation"] | None = None):
        return {"items": store.poll_all(group)}

    @app.get("/api/v1/events", response_model=EventPage)
    def events(monitor_id: str | None = None, kind: Literal["vessel","flight","aircraft"] | None = None,
               severity: Literal["high","warning","info"] | None = None,
               since: datetime | None = None, until: datetime | None = None,
               limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        start, end = utc(since).isoformat() if since else None, utc(until).isoformat() if until else None
        if start and end and start > end:
            raise ValueError("开始时间不能晚于结束时间")
        return store.events(monitor_id, kind, severity, start, end, limit, offset)

    @app.get("/api/v1/events/{event_id}", response_model=EventDetail)
    def event(event_id: str):
        return store.event_detail(event_id)

    @app.get("/api/v1/dashboard", response_model=DashboardOut)
    def dashboard():
        return portal.dashboard()

    @app.get("/api/v1/timeline", response_model=TimelinePage)
    def timeline(limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 snapshot: int | None = Query(default=None, ge=0), kind: Literal["vessel","flight","aircraft"] | None = None,
                 entry_type: Literal["all","events","quality"] = "all", severity: Literal["high","warning","info"] | None = None):
        return portal.timeline(limit, offset, snapshot, kind, entry_type, severity)

    @app.post("/api/v1/demo/seed", response_model=SeedOut)
    def seed_demo():
        return portal.seed()

    @app.get("/api/v1/news", response_model=list[NewsOut])
    def news():
        return portal.news()

    @app.post("/api/v1/news", status_code=201, response_model=NewsOut)
    def add_news(body: NewsCreate):
        return portal.add_news(body)

    @app.get("/api/v1/ai/status", response_model=AIStatus)
    def ai_status():
        return portal.status()

    @app.patch("/api/v1/ai/settings", response_model=AIStatus)
    def ai_settings(body: AISettings):
        return portal.configure(body)

    @app.post("/api/v1/ai/refresh", response_model=AIStatus)
    def ai_refresh():
        return portal.refresh()

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/asset-risk.html")

    @app.get("/asset-risk.html", include_in_schema=False)
    @app.get("/demo.html", include_in_schema=False)
    def page():
        return FileResponse(ROOT / "demo.html")

    return app
