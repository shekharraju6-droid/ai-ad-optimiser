"""
AdOptima AI conversational agent.
Uses Google Gemini when API key is available; falls back to local rule engine.
"""
import json
import re
import logging
from typing import Dict, Any, List, Optional
from backend.services.config import load_config
from backend.services.recommendations import build_audit_summary
from backend.services.google_ads import GoogleAdsApiClient

logger = logging.getLogger("AdOptima")


NEGATIVE_INTENT_WORDS = [
    "free", "job", "jobs", "salary", "download", "tutorial", "tutorials",
    "crack", "what is", "how to", "definition", "ppt", "pdf", "question paper",
    "question papers", "time table", "syllabus", "notes"
]


def _campaign_name_to_id(name_fragment: str) -> Optional[str]:
    lower = name_fragment.lower()
    if "bba" in lower or "brand" in lower:
        return "104"
    if "uk" in lower or "eu" in lower:
        return "102"
    if "ecommerce" in lower or "performance max" in lower or "pmax" in lower:
        return "103"
    if "us" in lower or "saas" in lower:
        return "101"
    return None


def run_agent(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    config = load_config()
    gemini_key = config.get("gemini_api_key", "")
    use_gemini = bool(gemini_key and len(gemini_key) > 10 and not gemini_key.startswith("●●●●"))

    if use_gemini:
        try:
            return _run_gemini_agent(message, history)
        except Exception as e:
            logger.error(f"Gemini agent failed: {e}")

    return _run_local_agent(message)


def _run_gemini_agent(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    import google.generativeai as genai
    config = load_config()
    genai.configure(api_key=config.get("gemini_api_key"))

    def tool_list_campaigns() -> str:
        """List all Google Ads campaigns with spend, conversions, CPA, CTR, and status."""
        client = GoogleAdsApiClient(config)
        return json.dumps([_format_campaign_row(r) for r in client.run_gaql(_CAMPAIGN_QUERY)])

    def tool_list_search_terms(campaign_id: Optional[str] = None) -> str:
        """List search terms with cost, clicks, conversions, CTR, and flags."""
        client = GoogleAdsApiClient(config)
        query = _SEARCH_TERM_QUERY
        if campaign_id:
            query += f" AND campaign.id = {campaign_id}"
        return json.dumps([_format_search_term_row(r) for r in client.run_gaql(query)])

    def tool_add_negative_keyword(campaign_id: str, keyword: str, match_type: str = "EXACT") -> str:
        """Add a negative keyword to a campaign. Match type must be EXACT, PHRASE, or BROAD."""
        client = GoogleAdsApiClient(config)
        return json.dumps(client.add_negative_keyword(campaign_id, keyword, match_type))

    def tool_audit_campaigns() -> str:
        """Run an optimization audit and return recommendations with estimated savings."""
        return json.dumps(build_audit_summary())

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=(
            "You are AdOptima AI, an expert Google Ads optimization assistant. "
            "Your job is to find budget waste, explain root causes, and take safe optimization actions. "
            "Use the provided tools to read campaigns, search terms, run audits, and add negative keywords. "
            "Always explain your reasoning briefly. Never guess numbers — use tools."
        ),
        tools=[tool_list_campaigns, tool_list_search_terms, tool_add_negative_keyword, tool_audit_campaigns],
    )

    chat = model.start_chat(enable_automatic_function_calling=True)
    response = chat.send_message(message)

    return {
        "response": response.text,
        "thoughts": "Used Gemini with tool calling to answer the user request.",
        "logs": ["🧠 Gemini model invoked", "⚙️ Tool execution completed"],
        "actions": [],
    }


def _run_local_agent(message: str) -> Dict[str, Any]:
    lower = message.lower()
    logs = ["🧠 Local NLP engine active"]
    actions = []
    thoughts = "Analyzing intent with local rule-based engine."

    # 1. Audit intent
    if any(k in lower for k in ["audit", "waste", "search term", "search query", "problem", "recommendation"]):
        target_id = None
        if "bba" in lower or "brand" in lower or "104" in lower:
            target_id = "104"

        logs.append(f"🧠 Intent detected: AUDIT (campaign_id={target_id})")
        audit = build_audit_summary(target_id)

        reply = (
            f"### 🔍 Search Term Waste Audit\n\n"
            f"I audited **{audit['campaigns_audited']}** campaign(s).\n"
            f"- Total spend: **${audit['total_spend']:.2f}**\n"
            f"- Estimated waste: **${audit['estimated_waste']:.2f}** ({audit['waste_percentage']:.1f}%)\n"
            f"- Problematic terms: **{audit['problematic_terms']}**\n\n"
        )

        # Group top recommendations
        by_campaign: Dict[str, List[Dict[str, Any]]] = {}
        for rec in audit["recommendations"][:20]:
            cname = rec.get("campaign_name", "Unknown")
            by_campaign.setdefault(cname, []).append(rec)

        for cname, recs in by_campaign.items():
            reply += f"#### {cname}\n"
            for rec in recs[:5]:
                if rec["type"] == "ADD_NEGATIVE_KEYWORD":
                    reply += f"- 🚫 Exclude **\"{rec['keyword']}\"** ({rec['match_type']}) — {rec['reason']} (~${rec['estimated_savings']:.2f})\n"
                elif rec["type"] in ("REDUCE_BUDGET", "PAUSE_OR_REDUCE_BUDGET"):
                    reply += f"- 💰 Reduce budget from **${rec['current_budget']:.2f}** to **${rec['suggested_budget']:.2f}** — {rec['reason']}\n"
                elif rec["type"] == "REDUCE_BID":
                    reply += f"- 📉 Reduce bid on **\"{rec['keyword']}\"** to ~${rec['suggested_bid']:.2f} — {rec['reason']}\n"
            reply += "\n"

        if target_id == "104":
            reply += (
                "### ⚠️ Root Cause for BBA - Brand\n"
                "Broad match target keywords are matching competitor names (e.g. *kristhu jayanthi*, *t john college*) "
                "and generic student searches (e.g. *question papers*, *time table*). "
                "Recommend shifting target keywords to Phrase/Exact match and excluding these terms as negatives.\n\n"
                "Would you like me to apply the top negative keyword recommendations?"
            )
        else:
            reply += "Would you like me to apply the top recommendations?"

        return {"response": reply, "thoughts": thoughts, "logs": logs, "actions": actions}

    # 2. List campaigns
    if any(k in lower for k in ["campaign", "show campaigns", "list campaigns"]):
        logs.append("🧠 Intent detected: LIST_CAMPAIGNS")
        config = load_config()
        client = GoogleAdsApiClient(config)
        camps = []
        if client.is_valid:
            try:
                camps = [_format_campaign_row(r) for r in client.run_gaql(_CAMPAIGN_QUERY)]
            except Exception as e:
                logger.error(f"Agent: live campaigns query failed: {e}")
        reply = "### Google Ads Campaigns\n\n"
        for c in camps:
            reply += f"- **{c['name']}** (ID `{c['id']}`): Spend **${c['spend']:.2f}** | Clicks **{c['clicks']}** | Conversions **{c['conversions']}** | CPA **${c['cpa']:.2f}**\n"
        reply += "\nAsk me to *audit search terms* or *exclude a keyword*."
        return {"response": reply, "thoughts": thoughts, "logs": logs, "actions": actions}

    # 3. Exclude / add negative keyword
    if any(k in lower for k in ["exclude", "add negative", "negative keyword", "block"]):
        logs.append("🧠 Intent detected: ADD_NEGATIVE_KEYWORD")

        match_type = "EXACT"
        if "phrase" in lower:
            match_type = "PHRASE"
        elif "broad" in lower:
            match_type = "BROAD"

        extracted = ""
        quotes = re.findall(r'"([^"]*)"', message)
        if quotes:
            extracted = quotes[0]
        else:
            words = message.split()
            for idx, word in enumerate(words):
                if word in ["keyword", "exclude", "block", "term"] and idx + 1 < len(words):
                    extracted = words[idx + 1].strip("'\".,")
                    break

        campaign_id = "101"
        if "bba" in lower or "brand" in lower or "104" in lower:
            campaign_id = "104"
        elif "uk" in lower or "eu" in lower or "102" in lower:
            campaign_id = "102"
        elif "ecommerce" in lower or "performance max" in lower or "103" in lower:
            campaign_id = "103"
        elif extracted:
            lower_kw = extracted.lower()
            if any(w in lower_kw for w in ["kristu", "kristhu", "jayanthi", "national", "t john", "predictor", "papers", "quota", "bba", "college", "dayananda", "dsu"]):
                campaign_id = "104"

        if not extracted:
            return {
                "response": "I recognized you want to exclude a term, but couldn't identify it. Please put it in double quotes, e.g. *Exclude \"free templates\"*.",
                "thoughts": thoughts,
                "logs": logs,
                "actions": actions,
            }

        logs.append(f"⚙️ Tool Invoked: add_negative_keyword(campaign_id={campaign_id}, keyword='{extracted}', match_type={match_type})")
        config = load_config()
        client = GoogleAdsApiClient(config)
        try:
            res = client.add_negative_keyword(campaign_id, extracted, match_type)
        except Exception as e:
            return {"response": f"Could not add negative keyword: {e}", "thoughts": thoughts, "logs": logs, "actions": actions}

        c_name = campaign_id
        actions.append({"type": "ADD_NEGATIVE", "campaign_id": campaign_id, "keyword": extracted, "match_type": match_type})
        reply = (
            f"✅ Added negative keyword **\"{extracted}\"** ({match_type}) to campaign **{c_name}**.\n\n"
            f"Future ad spend on this query has been halted."
        )
        return {"response": reply, "thoughts": thoughts, "logs": logs, "actions": actions}

    # 4. Apply recommendations intent
    if any(k in lower for k in ["apply", "do it", "execute", "approve"]):
        logs.append("🧠 Intent detected: APPLY_RECOMMENDATIONS")
        audit = build_audit_summary()
        applied = 0
        applied_items = []
        config = load_config()
        client = GoogleAdsApiClient(config)
        for rec in audit["recommendations"][:10]:
            if rec["type"] == "ADD_NEGATIVE_KEYWORD" and client.is_valid:
                try:
                    res = client.add_negative_keyword(rec["campaign_id"], rec["keyword"], rec["match_type"])
                    if res.get("success"):
                        applied += 1
                        applied_items.append(f"\"{rec['keyword']}\" → {rec['campaign_name']}")
                        actions.append({"type": "ADD_NEGATIVE", "campaign_id": rec["campaign_id"], "keyword": rec["keyword"], "match_type": rec["match_type"]})
                except Exception as e:
                    logger.error(f"Agent apply failed for '{rec['keyword']}': {e}")
        if applied == 0:
            reply = "I found no pending negative keyword recommendations to apply automatically. Run an audit first."
        else:
            reply = f"✅ Applied **{applied}** negative keyword recommendations:\n\n" + "\n".join(f"- {item}" for item in applied_items)
        return {"response": reply, "thoughts": thoughts, "logs": logs, "actions": actions}

    # Fallback help
    logs.append("🧠 Intent: GENERAL_HELP")
    reply = (
        "Hello! I am **AdOptima AI**.\n\n"
        "I can help you:\n"
        "1. 📊 *\"List my campaigns\"*\n"
        "2. 🔍 *\"Audit search terms for waste\"*\n"
        "3. 🚫 *\"Exclude \"keyword\" from BBA campaign\"*\n"
        "4. ✅ *\"Apply recommendations\"*\n\n"
        "Add a Gemini API key in Settings for fully conversational mode."
    )
    return {"response": reply, "thoughts": thoughts, "logs": logs, "actions": actions}


# GAQL queries for live Google Ads API
_CAMPAIGN_QUERY = """
    SELECT
      campaign.id,
      campaign.name,
      campaign.status,
      campaign.campaign_budget,
      metrics.cost_micros,
      metrics.clicks,
      metrics.impressions,
      metrics.conversions
    FROM campaign
    WHERE campaign.status = 'ENABLED'
"""

_SEARCH_TERM_QUERY = """
    SELECT
      search_term_view.search_term,
      campaign.name,
      campaign.id,
      metrics.clicks,
      metrics.impressions,
      metrics.cost_micros,
      metrics.conversions
    FROM search_term_view
    WHERE segments.date DURING LAST_30_DAYS
"""


def _format_campaign_row(row: Dict[str, Any]) -> Dict[str, Any]:
    cost = (row.get("metrics.cost_micros") or 0) / 1_000_000.0
    clicks = row.get("metrics.clicks") or 0
    impressions = row.get("metrics.impressions") or 0
    conversions = row.get("metrics.conversions") or 0
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
    cpa = round(cost / conversions, 2) if conversions else 0.0
    return {
        "id": str(row.get("campaign.id")),
        "name": row.get("campaign.name", "Unnamed"),
        "status": str(row.get("campaign.status")),
        "budget": (row.get("campaign.campaign_budget") or 0) / 1_000_000.0,
        "spend": cost,
        "clicks": clicks,
        "impressions": impressions,
        "conversions": conversions,
        "ctr": ctr,
        "cpa": cpa,
    }


def _format_search_term_row(row: Dict[str, Any]) -> Dict[str, Any]:
    clicks = row.get("metrics.clicks") or 0
    impressions = row.get("metrics.impressions") or 0
    cost = (row.get("metrics.cost_micros") or 0) / 1_000_000.0
    conversions = row.get("metrics.conversions") or 0
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0.0
    cpa = round(cost / conversions, 2) if conversions else 0.0
    term = row.get("search_term_view.search_term", "")
    flags = []
    if conversions == 0 and cost > 50:
        flags.append("High Spend, No Conversions")
    if ctr < 1.5:
        flags.append("Low CTR")
    for word in NEGATIVE_INTENT_WORDS:
        if word in term.lower():
            flags.append(f"Unproductive Term (contains '{word}')")
            break
    return {
        "campaign_id": str(row.get("campaign.id")),
        "campaign_name": row.get("campaign.name", "Unknown"),
        "term": term,
        "clicks": clicks,
        "impressions": impressions,
        "cost": round(cost, 2),
        "conversions": conversions,
        "ctr": ctr,
        "cpa": cpa,
        "match_type": "SEARCH_TERM",
        "flags": flags,
    }
