"""
AdOptima AI - Google Ads Optimization Assistant
FastAPI application entry point.
"""
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import config, campaigns, search_terms, negatives, optimizations, logs, chat, auth, reports, accounts, audits, notifications, oauth
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

# Initialize database tables and scheduler
init_db()
start_scheduler()


@app.get("/", response_class=HTMLResponse)
def get_ui(request: Request):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    html_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Frontend UI not found.</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
