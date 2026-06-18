"""
Per-account mock Google Ads / Meta Ads data generator for testing the audit engine.
Deterministic mock data is created based on account name and platform.
"""
import random
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes", "sample", "template"
]

EDUCATION_WASTE_TERMS = [
    "kristhu jayanthi", "t john college", "national college basavanagudi",
    "bangalore technological institute", "college predictor", "college fees",
    "college address", "admission", "syllabus", "question papers", "time table",
    "fees structure", "management quota", "distance", "part time"
]

REAL_ESTATE_WASTE_TERMS = [
    "rent", "lease", "broker", "agent", "price per sqft", "resale",
    "old property", "legal issue", "complaint", "review", "rating"
]

HEALTHCARE_WASTE_TERMS = [
    "job", "career", "salary", "doctor list", "phone number", "address",
    "free checkup", "government hospital", "home remedy", "symptoms"
]


def _seed(name: str) -> random.Random:
    """Return a deterministic random generator for an account name."""
    return random.Random(sum(ord(c) for c in name) + 42)


def _random_url(rng: random.Random, domain: str, path: str, with_utm: bool = True) -> str:
    base = f"https://{domain}/{path}"
    if with_utm:
        base += f"?utm_source={rng.choice(['google','meta'])}"
        base += f"\u0026utm_medium={rng.choice(['cpc','paid'])}"
        base += f"\u0026utm_campaign={path.replace('/', '_')}"
    return base


def generate_google_mock_data(account_name: str, external_id: str) -> Dict[str, Any]:
    rng = _seed(account_name)
    lower = account_name.lower()

    # Theme based on account name
    if "dsu" in lower or "dsi" in lower or "education" in lower or "college" in lower or "university" in lower:
        theme = "education"
        domain = "dayanandasagar.edu"
        campaign_prefixes = [
            ("BBA Brand Search", "bba"),
            ("MBA Lead Gen", "mba"),
            ("Engineering Admissions", "btech"),
            ("Generic University Queries", "university"),
        ]
    elif "steel" in lower or "manufacturing" in lower or "featherlite" in lower or "ifs" in lower:
        theme = "b2b"
        domain = "shyamsteel.com" if "steel" in lower else "classicfeatherlite.com"
        campaign_prefixes = [
            ("Product Search - TMT Bars", "tmt-bars"),
            ("Dealer Locator", "dealers"),
            ("Brand Awareness", "brand"),
            ("Competitor Conquesting", "conquest"),
        ]
    elif "mantri" in lower or "surya" in lower or "real estate" in lower or "developer" in lower:
        theme = "realestate"
        domain = "mantri.in" if "mantri" in lower else "suryadevelopers.com"
        campaign_prefixes = [
            ("Luxury Apartments", "apartments"),
            ("Villa Projects", "villas"),
            ("Location-Based Search", "location"),
            ("Brand Search", "brand"),
        ]
    elif "sparsh" in lower or "hospital" in lower or "health" in lower or "gym" in lower or "little gym" in lower:
        theme = "healthcare"
        domain = "sparshhospital.com" if "sparsh" in lower else "thelittlegym.in"
        campaign_prefixes = [
            ("Specialty Services", "specialty"),
            ("Doctor Search", "doctors"),
            ("Book Appointment", "appointment"),
            ("Brand Search", "brand"),
        ]
    else:
        theme = "generic"
        domain = "example.com"
        campaign_prefixes = [
            ("Brand Search", "brand"),
            ("Generic Search", "generic"),
            ("Competitor", "competitor"),
            ("Remarketing", "remarketing"),
        ]

    campaigns = []
    keywords = []
    search_terms = []
    negatives = {}

    for idx, (camp_name, path) in enumerate(campaign_prefixes):
        camp_id = f"camp_{idx + 1}"
        budget = rng.choice([50000, 75000, 100000, 150000])
        spend_ratio = rng.uniform(0.55, 0.95)
        spend = round(budget * spend_ratio, 2)
        conversions = rng.randint(0, 120)
        clicks = rng.randint(200, 5000)
        impressions = clicks * rng.randint(15, 80)
        ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
        cpa = round(spend / conversions, 2) if conversions else 0.0

        # Campaign setup issues injected deterministically
        issues = []
        if idx == 0 and rng.random() < 0.7:
            issues.append("conversion_tracking_missing")
        if idx == 1 and rng.random() < 0.5:
            issues.append("landing_page_404")
        if idx == 2 and rng.random() < 0.6:
            issues.append("no_negative_keywords")
        if rng.random() < 0.3:
            issues.append("only_broad_match")

        final_url = _random_url(rng, domain, path, with_utm=("landing_page_404" not in issues))
        if "landing_page_404" in issues:
            final_url = final_url.replace(domain, "broken-" + domain)

        campaigns.append({
            "id": camp_id,
            "name": camp_name,
            "status": "ENABLED" if rng.random() < 0.85 else "PAUSED",
            "budget": budget,
            "spend": spend,
            "clicks": clicks,
            "impressions": impressions,
            "conversions": conversions,
            "ctr": ctr,
            "cpa": cpa,
            "target_cpa": round(budget / (rng.randint(50, 150)), 2),
            " bidding_strategy": rng.choice(["MANUAL_CPC", "TARGET_CPA", "MAXIMIZE_CONVERSIONS", "TARGET_ROAS"]),
            "ad_rotation": rng.choice(["OPTIMIZE", "ROTATE_FOREVER", "ROTATE_INDEFINITELY"]),
            "start_date": (datetime.utcnow() - timedelta(days=rng.randint(30, 180))).strftime("%Y-%m-%d"),
            "end_date": None,
            "location_targeting": rng.choice(["Bangalore", "Karnataka", "India", "All India"]),
            "network_setting": rng.choice(["Search", "Search + Display", "Search + Partners"]),
            "conversion_tracking_enabled": "conversion_tracking_missing" not in issues,
            "landing_page_url": final_url,
            "landing_page_status": 404 if "landing_page_404" in issues else 200,
            "issues": issues,
        })

        # Generate keywords per campaign
        kw_count = rng.randint(5, 12)
        for kidx in range(kw_count):
            kw_text = _keyword_for_theme(theme, rng, camp_name)
            match_type = rng.choice(["BROAD", "PHRASE", "EXACT"])
            if "only_broad_match" in issues:
                match_type = "BROAD"
            kw_spend = round(rng.uniform(500, spend * 0.3), 2)
            kw_conversions = rng.randint(0, max(1, conversions // 3))
            kw_clicks = rng.randint(10, max(20, clicks // 4))
            kw_impressions = kw_clicks * rng.randint(10, 60)
            kw_ctr = round((kw_clicks / kw_impressions) * 100, 2) if kw_impressions else 0.0
            kw_cpa = round(kw_spend / kw_conversions, 2) if kw_conversions else 0.0
            quality_score = rng.randint(1, 10)

            keywords.append({
                "campaign_id": camp_id,
                "ad_group_id": f"ag_{camp_id}",
                "criterion_id": f"kw_{camp_id}_{kidx}",
                "text": kw_text,
                "match_type": match_type,
                "bid": round(rng.uniform(20, 120), 2),
                "spend": kw_spend,
                "clicks": kw_clicks,
                "impressions": kw_impressions,
                "conversions": kw_conversions,
                "ctr": kw_ctr,
                "cpa": kw_cpa,
                "quality_score": quality_score,
            })

        # Generate search terms per campaign
        term_count = rng.randint(8, 20)
        for tidx in range(term_count):
            term = _search_term_for_theme(theme, rng, camp_name)
            cost = round(rng.uniform(200, 2000), 2)
            term_clicks = rng.randint(1, 50)
            term_impressions = term_clicks * rng.randint(5, 40)
            term_conversions = rng.randint(0, 2)
            if any(w in term.lower() for w in NEGATIVE_INTENT_WORDS + _waste_terms(theme)):
                term_conversions = 0
            term_ctr = round((term_clicks / term_impressions) * 100, 2) if term_impressions else 0.0
            term_cpa = round(cost / term_conversions, 2) if term_conversions else 0.0
            search_terms.append({
                "campaign_id": camp_id,
                "campaign_name": camp_name,
                "term": term,
                "clicks": term_clicks,
                "impressions": term_impressions,
                "cost": cost,
                "conversions": term_conversions,
                "ctr": term_ctr,
                "cpa": term_cpa,
                "match_type": rng.choice(["BROAD", "PHRASE", "EXACT"]),
            })

        # Existing negatives
        negatives[camp_id] = []
        if "no_negative_keywords" not in issues and rng.random() < 0.5:
            negatives[camp_id] = [{"text": "free", "match_type": "PHRASE"}]

    return {
        "theme": theme,
        "campaigns": campaigns,
        "keywords": keywords,
        "search_terms": search_terms,
        "negatives": negatives,
    }


def _keyword_for_theme(theme: str, rng: random.Random, camp_name: str) -> str:
    if theme == "education":
        return rng.choice([
            "bba admissions", "mba colleges bangalore", "engineering admissions",
            "best university in bangalore", "btech computer science", "mba fees",
            "university ranking", "dayananda sagar university", "dsu courses",
            "bca admission", "mtech colleges", "pharmacy college"
        ])
    if theme == "b2b":
        return rng.choice([
            "tmt steel bars", "steel dealers", "construction materials",
            "featherlite furniture", "office chairs bulk", "modular furniture",
            "fire safety systems", "fire extinguisher supplier", "b2b steel supplier"
        ])
    if theme == "realestate":
        return rng.choice([
            "luxury apartments bangalore", "villas for sale", "2 bhk flats",
            "new projects bangalore", "premium apartments", "property developer",
            "3 bhk whitefield", "ready to move flats", "apartments near me"
        ])
    if theme == "healthcare":
        return rng.choice([
            "best hospital bangalore", "cardiologist near me", "orthopedic doctor",
            "kids gym classes", "children fitness", "pediatric hospital",
            "book doctor appointment", "maternity hospital", "physiotherapy clinic"
        ])
    return rng.choice(["brand search", "generic product", "competitor keyword", "service keyword"])


def _search_term_for_theme(theme: str, rng: random.Random, camp_name: str) -> str:
    if theme == "education":
        good = ["dsu bba admission 2026", "dayananda sagar university mba", "engineering admission dsu"]
        bad = [
            "kristhu jayanthi college bba fees", "t john college bangalore", "bba question papers pdf",
            "national college basavanagudi address", "free mba notes download", "bba time table 2026",
            "dayananda sagar management quota fees", "college predictor 2026", "top engineering colleges bangalore",
            "distance bba course", "part time mba fees", "mba salary after graduation"
        ]
        return rng.choice(good + bad)
    if theme == "b2b":
        good = ["buy tmt bars bangalore", "steel supplier contact", "featherlite office furniture dealer"]
        bad = ["free steel price list", "steel company jobs", "how to make steel", "ppt on steel manufacturing"]
        return rng.choice(good + bad)
    if theme == "realestate":
        good = ["buy 2 bhk mantri apartment", "surya developers new project", "luxury villas bangalore"]
        bad = ["apartment for rent", "property broker salary", "old flats resale", "legal issues mantri"]
        return rng.choice(good + bad)
    if theme == "healthcare":
        good = ["book sparsh hospital appointment", "best pediatrician bangalore", "kids gym near me"]
        bad = ["hospital staff nurse job", "doctor salary india", "free health checkup", "home remedy back pain"]
        return rng.choice(good + bad)
    return rng.choice(["relevant query", "waste query free", "competitor query", "informational query"])


def _waste_terms(theme: str) -> List[str]:
    if theme == "education":
        return EDUCATION_WASTE_TERMS
    if theme == "realestate":
        return REAL_ESTATE_WASTE_TERMS
    if theme == "healthcare":
        return HEALTHCARE_WASTE_TERMS
    return []


def generate_meta_mock_data(account_name: str, external_id: str) -> Dict[str, Any]:
    rng = _seed(account_name + "_meta")
    campaigns = []
    adsets = []
    ads = []
    for idx in range(rng.randint(2, 4)):
        camp_id = f"mcamp_{idx + 1}"
        budget = rng.choice([30000, 50000, 80000])
        spend = round(budget * rng.uniform(0.5, 0.95), 2)
        conversions = rng.randint(0, 80)
        clicks = rng.randint(300, 4000)
        impressions = clicks * rng.randint(20, 70)
        ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
        cpa = round(spend / conversions, 2) if conversions else 0.0
        campaigns.append({
            "id": camp_id,
            "name": f"Meta Campaign {idx + 1} - {account_name}",
            "status": "ACTIVE" if rng.random() < 0.85 else "PAUSED",
            "objective": rng.choice(["LEAD_GENERATION", "CONVERSIONS", "TRAFFIC", "AWARENESS"]),
            "budget": budget,
            "spend": spend,
            "clicks": clicks,
            "impressions": impressions,
            "conversions": conversions,
            "ctr": ctr,
            "cpa": cpa,
            "target_cpa": round(budget / (rng.randint(40, 120)), 2),
            "attribution_window": rng.choice(["7d_click", "1d_view", "28d_click"]),
            "pixel_status": rng.choice(["ACTIVE", "UNVERIFIED", "NO_RECENT_ACTIVITY"]),
            "issues": []
        })
        if campaigns[-1]["pixel_status"] != "ACTIVE":
            campaigns[-1]["issues"].append("pixel_not_active")
        if spend > budget * 0.8 and conversions == 0:
            campaigns[-1]["issues"].append("high_spend_no_conversions")

        for aidx in range(rng.randint(2, 4)):
            adsets.append({
                "campaign_id": camp_id,
                "id": f"adset_{camp_id}_{aidx}",
                "name": f"AdSet {aidx + 1}",
                "status": "ACTIVE",
                "budget": round(budget / 3, 2),
                "spend": round(spend / 3, 2),
                "clicks": clicks // 3,
                "impressions": impressions // 3,
                "conversions": conversions // 3,
                "ctr": ctr,
                "cpa": cpa,
                "audience": rng.choice(["Lookalike 1%", "Interest - Education", "Retargeting", "Broad"]),
                "placement": rng.choice(["Feed", "Stories", "Reels", "All Placements"]),
            })

        for adidx in range(rng.randint(2, 5)):
            ads.append({
                "campaign_id": camp_id,
                "adset_id": f"adset_{camp_id}_0",
                "id": f"ad_{camp_id}_{adidx}",
                "name": f"Ad {adidx + 1}",
                "status": "ACTIVE",
                "ctr": round(ctr * rng.uniform(0.5, 1.5), 2),
                "headline": rng.choice(["Apply Now", "Learn More", "Book a Call", "Enroll Today"]),
                "landing_page_url": f"https://example.com/meta/{camp_id}?utm_source=meta\u0026utm_medium=paid" if rng.random() > 0.3 else f"https://example.com/meta/{camp_id}",
            })

    return {
        "theme": "meta",
        "campaigns": campaigns,
        "adsets": adsets,
        "ads": ads,
    }
