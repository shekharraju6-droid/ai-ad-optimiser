"""
In-memory mock Google Ads database used when mock_mode=True.
"""
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("AdOptima")

NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes"
]


class MockGoogleAdsDb:
    def __init__(self):
        self.reset()

    def reset(self):
        self.campaigns = [
            {
                "id": "101",
                "name": "US - SaaS Platform - Broad Match",
                "status": "ENABLED",
                "budget": 2000.00,
                "spend": 1240.50,
                "clicks": 450,
                "impressions": 8900,
                "conversions": 12,
                "ctr": 5.06,
                "cpa": 103.38,
                "target_cpa": 80.00,
            },
            {
                "id": "102",
                "name": "UK & EU - SaaS Lead Gen - Phrase Match",
                "status": "ENABLED",
                "budget": 1500.00,
                "spend": 850.20,
                "clicks": 310,
                "impressions": 6200,
                "conversions": 8,
                "ctr": 5.00,
                "cpa": 106.28,
                "target_cpa": 90.00,
            },
            {
                "id": "103",
                "name": "E-Commerce - Performance Max",
                "status": "ENABLED",
                "budget": 5000.00,
                "spend": 3200.75,
                "clicks": 1450,
                "impressions": 45000,
                "conversions": 112,
                "ctr": 3.22,
                "cpa": 28.58,
                "target_cpa": 30.00,
            },
            {
                "id": "104",
                "name": "BBA - Brand",
                "status": "ENABLED",
                "budget": 50000.00,
                "spend": 43546.38,
                "clicks": 1506,
                "impressions": 44448,
                "conversions": 0,
                "ctr": 3.39,
                "cpa": 0.00,
                "target_cpa": 0.00,
            },
        ]

        self.negatives = {
            "101": [
                {"id": "n1", "text": "free templates", "match_type": "PHRASE"},
                {"id": "n2", "text": "jobs in software", "match_type": "PHRASE"},
                {"id": "n3", "text": "resume builder", "match_type": "EXACT"},
            ],
            "102": [{"id": "n4", "text": "crm ppt", "match_type": "BROAD"}],
            "103": [],
            "104": [{"id": "n5", "text": "dsu bangalore address", "match_type": "EXACT"}],
        }

        self.all_search_terms = {
            "101": [
                {"term": "salesforce integration software", "clicks": 120, "impressions": 1500, "cost": 350.00, "conversions": 8, "match_type": "BROAD"},
                {"term": "google ads automation tool", "clicks": 80, "impressions": 1000, "cost": 240.00, "conversions": 3, "match_type": "BROAD"},
                {"term": "free project management software download", "clicks": 90, "impressions": 2200, "cost": 180.00, "conversions": 0, "match_type": "BROAD"},
                {"term": "software developer salary in usa", "clicks": 50, "impressions": 1200, "cost": 100.00, "conversions": 0, "match_type": "BROAD"},
                {"term": "jobs at SaaS software company", "clicks": 40, "impressions": 800, "cost": 90.00, "conversions": 0, "match_type": "BROAD"},
                {"term": "best pipeline tracking CRM", "clicks": 60, "impressions": 1800, "cost": 260.00, "conversions": 1, "match_type": "BROAD"},
                {"term": "crack software full version free", "clicks": 10, "impressions": 600, "cost": 20.50, "conversions": 0, "match_type": "BROAD"},
            ],
            "102": [
                {"term": "enterprise CRM pricing", "clicks": 150, "impressions": 2500, "cost": 450.00, "conversions": 5, "match_type": "PHRASE"},
                {"term": "hire CRM consultant", "clicks": 80, "impressions": 1200, "cost": 220.00, "conversions": 2, "match_type": "PHRASE"},
                {"term": "CRM ppt presentation download", "clicks": 50, "impressions": 1500, "cost": 100.00, "conversions": 0, "match_type": "PHRASE"},
                {"term": "crm definition", "clicks": 30, "impressions": 1000, "cost": 80.20, "conversions": 1, "match_type": "PHRASE"},
            ],
            "103": [
                {"term": "buy shoes online free shipping", "clicks": 800, "impressions": 20000, "cost": 1500.00, "conversions": 75, "match_type": "BROAD"},
                {"term": "running shoes cheap sales", "clicks": 500, "impressions": 18000, "cost": 1200.75, "conversions": 32, "match_type": "BROAD"},
                {"term": "how to make a shoe at home", "clicks": 150, "impressions": 7000, "cost": 500.00, "conversions": 5, "match_type": "BROAD"},
            ],
            "104": [
                {"term": "dsu admission", "clicks": 2, "impressions": 5, "cost": 122.34, "conversions": 0, "match_type": "BROAD"},
                {"term": "kristhu jayanthi", "clicks": 1, "impressions": 1, "cost": 56.74, "conversions": 0, "match_type": "BROAD"},
                {"term": "dsu bangalore address", "clicks": 1, "impressions": 4, "cost": 50.87, "conversions": 0, "match_type": "BROAD"},
                {"term": "dsu main campus fees structure", "clicks": 2, "impressions": 4, "cost": 97.82, "conversions": 0, "match_type": "BROAD"},
                {"term": "bba subject", "clicks": 2, "impressions": 35, "cost": 95.69, "conversions": 0, "match_type": "BROAD"},
                {"term": "bba college fees", "clicks": 1, "impressions": 2, "cost": 46.18, "conversions": 0, "match_type": "BROAD"},
                {"term": "dayananda sagar college of law fees", "clicks": 2, "impressions": 4, "cost": 92.14, "conversions": 0, "match_type": "BROAD"},
                {"term": "dayananda sagar college of law", "clicks": 1, "impressions": 15, "cost": 45.48, "conversions": 0, "match_type": "BROAD"},
                {"term": "address of dayananda sagar university bangalore", "clicks": 2, "impressions": 1, "cost": 90.42, "conversions": 0, "match_type": "BROAD"},
                {"term": "bba course", "clicks": 17, "impressions": 546, "cost": 759.85, "conversions": 0, "match_type": "BROAD"},
                {"term": "degree college application", "clicks": 1, "impressions": 1, "cost": 42.99, "conversions": 0, "match_type": "BROAD"},
                {"term": "top10 engineering colleges in bangalore", "clicks": 1, "impressions": 1, "cost": 41.45, "conversions": 0, "match_type": "BROAD"},
                {"term": "national college basavanagudi", "clicks": 2, "impressions": 22, "cost": 82.88, "conversions": 0, "match_type": "BROAD"},
                {"term": "bangalore technological institute", "clicks": 1, "impressions": 5, "cost": 41.42, "conversions": 0, "match_type": "BROAD"},
                {"term": "college predictor", "clicks": 1, "impressions": 7, "cost": 41.41, "conversions": 0, "match_type": "BROAD"},
                {"term": "bba time table 2026", "clicks": 1, "impressions": 5, "cost": 41.40, "conversions": 0, "match_type": "BROAD"},
                {"term": "t john college bba fees", "clicks": 1, "impressions": 1, "cost": 41.38, "conversions": 0, "match_type": "BROAD"},
                {"term": "top ten engineering colleges in bangalore", "clicks": 2, "impressions": 2, "cost": 82.74, "conversions": 0, "match_type": "BROAD"},
                {"term": "dayananda sagar innovation campus", "clicks": 2, "impressions": 12, "cost": 82.70, "conversions": 0, "match_type": "BROAD"},
                {"term": "bengaluru city university question papers with answers pdf", "clicks": 1, "impressions": 2, "cost": 41.32, "conversions": 0, "match_type": "BROAD"},
                {"term": "dayananda sagar management quota fees for cse", "clicks": 1, "impressions": 11, "cost": 41.27, "conversions": 0, "match_type": "BROAD"},
                {"term": "dayananda university", "clicks": 1, "impressions": 23, "cost": 41.24, "conversions": 0, "match_type": "BROAD"},
            ],
        }

        self.action_logs = [
            {"time": "Initial State", "type": "SYSTEM", "message": "Mock Google Ads account database initialized."}
        ]
        self.initial_spend_by_campaign = {c["id"]: c["spend"] for c in self.campaigns}

    def add_action_log(self, log_type: str, message: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.action_logs.append({"time": now, "type": log_type, "message": message})
        logger.info(f"[{log_type}] {message}")

    def is_keyword_excluded(self, search_term: str, neg_keyword: str, match_type: str) -> bool:
        search_term = search_term.lower().strip()
        neg = neg_keyword.lower().strip()
        if match_type == "EXACT":
            return search_term == neg
        if match_type == "PHRASE":
            return neg in search_term
        neg_words = neg.split()
        search_words = search_term.split()
        return all(w in search_words for w in neg_words)

    def get_filtered_search_terms(self, campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
        results = []
        campaign_ids = [campaign_id] if campaign_id else list(self.all_search_terms.keys())

        for c_id in campaign_ids:
            if c_id not in self.all_search_terms:
                continue
            campaign_negatives = self.negatives.get(c_id, [])
            campaign_name = next((c["name"] for c in self.campaigns if c["id"] == c_id), "Unknown")

            for st in self.all_search_terms[c_id]:
                excluded = any(
                    self.is_keyword_excluded(st["term"], neg["text"], neg["match_type"])
                    for neg in campaign_negatives
                )
                if excluded:
                    continue

                ctr = round((st["clicks"] / st["impressions"]) * 100, 2) if st["impressions"] > 0 else 0.0
                cpa = round(st["cost"] / st["conversions"], 2) if st["conversions"] > 0 else 0.0
                flags = self._flag_term(st)

                results.append({
                    "campaign_id": c_id,
                    "campaign_name": campaign_name,
                    "term": st["term"],
                    "clicks": st["clicks"],
                    "impressions": st["impressions"],
                    "cost": round(st["cost"], 2),
                    "conversions": st["conversions"],
                    "ctr": ctr,
                    "cpa": cpa,
                    "match_type": st["match_type"],
                    "flags": flags,
                })
        return results

    def _flag_term(self, st: Dict[str, Any]) -> List[str]:
        flags = []
        lower_term = st["term"].lower()
        clicks = st.get("clicks", 0)
        impressions = st.get("impressions", 0)
        ctr = round((clicks / impressions) * 100, 2) if impressions > 0 else 0.0
        if st.get("conversions", 0) == 0 and st.get("cost", 0) > 50:
            flags.append("High Spend, No Conversions")
        if ctr < 1.5:
            flags.append("Low CTR (Poor Relevance)")
        for word in NEGATIVE_INTENT_WORDS:
            if word in lower_term:
                flags.append(f"Unproductive Term (contains '{word}')")
                break
        # Generic competitor/college intent heuristic for BBA-like campaigns
        if any(x in lower_term for x in ["college", "university", "fees", "address", "admission"]):
            if "dsu" not in lower_term and "dayananda" not in lower_term:
                flags.append("Possible Competitor / Generic Intent")
        return flags

    def add_negative_keyword(self, campaign_id: str, keyword: str, match_type: str = "EXACT") -> Dict[str, Any]:
        if campaign_id not in self.negatives:
            self.negatives[campaign_id] = []

        keyword = keyword.strip()
        for neg in self.negatives[campaign_id]:
            if neg["text"].lower() == keyword.lower() and neg["match_type"] == match_type:
                return {"success": False, "message": f"Negative keyword '{keyword}' already exists in campaign {campaign_id}"}

        new_id = f"n{len(self.negatives) + len(self.negatives[campaign_id]) + 1}"
        new_neg = {"id": new_id, "text": keyword, "match_type": match_type}
        self.negatives[campaign_id].append(new_neg)

        campaign = next((c for c in self.campaigns if c["id"] == campaign_id), None)
        if campaign:
            saved_cost = sum(
                st["cost"] for st in self.all_search_terms.get(campaign_id, [])
                if self.is_keyword_excluded(st["term"], keyword, match_type)
            )
            if saved_cost > 0:
                campaign["spend"] = max(0.0, round(campaign["spend"] - saved_cost, 2))
                campaign["cpa"] = round(campaign["spend"] / campaign["conversions"], 2) if campaign["conversions"] > 0 else 0.0
                self.add_action_log(
                    "OPTIMIZATION",
                    f"Added negative keyword '{keyword}' ({match_type}) to '{campaign['name']}'. Simulated savings: ${saved_cost:.2f}.",
                )
            else:
                self.add_action_log("OPTIMIZATION", f"Added negative keyword '{keyword}' ({match_type}) to '{campaign['name']}'.")

        return {"success": True, "negative": new_neg}

    def update_campaign_budget(self, campaign_id: str, new_budget: float) -> Dict[str, Any]:
        campaign = next((c for c in self.campaigns if c["id"] == campaign_id), None)
        if not campaign:
            return {"success": False, "message": f"Campaign {campaign_id} not found"}
        old_budget = campaign["budget"]
        campaign["budget"] = round(new_budget, 2)
        self.add_action_log("OPTIMIZATION", f"Updated '{campaign['name']}' budget from ${old_budget:.2f} to ${new_budget:.2f}.")
        return {"success": True, "campaign": campaign}

    def update_keyword_bid(self, campaign_id: str, ad_group_id: str, criterion_id: str, new_bid: float) -> Dict[str, Any]:
        # Mock bid update; in real mode this calls AdGroupCriterionService.
        self.add_action_log("OPTIMIZATION", f"Updated bid to ${new_bid:.2f} for criterion {criterion_id} in ad group {ad_group_id}.")
        return {"success": True, "campaign_id": campaign_id, "ad_group_id": ad_group_id, "criterion_id": criterion_id, "new_bid": new_bid}


mock_db = MockGoogleAdsDb()
