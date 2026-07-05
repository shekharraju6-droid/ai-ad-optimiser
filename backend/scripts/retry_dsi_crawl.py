"""Retry crawling DSI landing pages only."""
import time
from backend.db.database import SessionLocal
from backend.services.landing_page_service import crawl_stale_landing_pages
from backend.db.models import CampaignLandingPage, Account

# Wait a bit to respect Gemini free-tier rate limits
time.sleep(70)

db = SessionLocal()
dsi = db.query(Account).filter(Account.name == "DSI").first()
print(f"DSI account id={dsi.id if dsi else 'NOT FOUND'}")
if dsi:
    before = db.query(CampaignLandingPage).filter(
        CampaignLandingPage.account_id == dsi.id,
        CampaignLandingPage.landing_page_content.isnot(None)
    ).count()
    print(f"Before crawl: {before} with content")
    result = crawl_stale_landing_pages(dsi.id, db=db)
    print(f"Crawl result: {result}")
    after = db.query(CampaignLandingPage).filter(
        CampaignLandingPage.account_id == dsi.id,
        CampaignLandingPage.landing_page_content.isnot(None)
    ).count()
    print(f"After crawl: {after} with content")
db.close()