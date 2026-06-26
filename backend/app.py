"""
AdOptima AI - Google Ads Optimization Assistant
FastAPI application entry point.
"""
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import config, campaigns, search_terms, negatives, optimizations, logs, chat, auth, reports, accounts, audits, notifications, oauth, crm, revenueops, dsu_report, dsi_report, mantri

from backend.db.database import init_db
from backend.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AdOptima")

app = FastAPI(title="AdOptima AI - Google Ads Optimization")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(config.router)
app.include_router(accounts.router)
app.include_router(campaigns.router)
app.include_router(search_terms.router)
app.include_router(negatives.router)
app.include_router(optimizations.router)
app.include_router(logs.router)
app.include_router(chat.router)
app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(audits.router)
app.include_router(notifications.router)
app.include_router(oauth.router)
app.include_router(crm.router)
app.include_router(dsu_report.router)
app.include_router(dsi_report.router)
app.include_router(revenueops.router)
app.include_router(mantri.router)


# Initialize database tables only at import time; scheduler starts lazily on first request
init_db()
_scheduler_started = False

def ensure_scheduler():
    global _scheduler_started
    if not _scheduler_started:
        try:
            start_scheduler()
            _scheduler_started = True
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")


@app.middleware("http")
async def lazy_start_scheduler(request, call_next):
    ensure_scheduler()
    return await call_next(request)


@app.get("/health")
def health_check():
    return {"status": "ok", "port": os.getenv("PORT", "8000")}


@app.get("/favicon.ico")
def get_favicon():
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    favicon_path = os.path.join(frontend_dir, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    # Return a 1x1 transparent GIF if no favicon exists to avoid 404 noise
    return HTMLResponse(content=b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;", media_type="image/gif")


@app.get("/", response_class=HTMLResponse)
def get_landing(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "landing.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>ChlearSakhaaOps AI landing page not found.</h1>")


@app.get("/adpulse", response_class=HTMLResponse)
def get_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AdPulse UI not found.</h1>")


@app.get("/insightdesk", response_class=HTMLResponse)
def get_mis_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "mis.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>InsightDesk UI not found.</h1>")


@app.get("/revenueops", response_class=HTMLResponse)
def get_revenueops_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "revenueops.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>RevenueOps UI not found.</h1>")


@app.get("/integrations", response_class=HTMLResponse)
def get_integrations_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "integrations.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Integrations UI not found.</h1>")


@app.get("/onboard", response_class=HTMLResponse)
def get_onboard_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "onboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Onboarding UI not found.</h1>")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host=host, port=port, reload=True)
