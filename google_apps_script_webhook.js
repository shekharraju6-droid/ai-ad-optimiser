/**
 * Meta Lead Ads Webhook Receiver for Google Sheets
 * Sheet: "JUNE | JULY 2026 - Goa Leads"
 * Columns: Lead Created, Source, Occasion, Budget, Purchase Timeline, Email ID, Full Name, Phone Number
 */

const SHEET_NAME = "JUNE | JULY 2026 - Goa Leads";
const META_TOKEN = PropertiesService.getScriptProperties().getProperty("META_TOKEN");

function doGet(e) {
  // Meta webhook verification
  if (e.parameter["hub.mode"] === "subscribe" && e.parameter["hub.challenge"]) {
    return ContentService.createTextOutput(e.parameter["hub.challenge"]);
  }
  return ContentService.createTextOutput("OK");
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const entry = payload.entry && payload.entry[0];
    if (!entry || !entry.changes) return ContentService.createTextOutput("No changes");

    for (const change of entry.changes) {
      if (change.field !== "leadgen") continue;

      const leadId = change.value.leadgen_id;
      const pageId = change.value.page_id;
      const formId = change.value.form_id;
      const adId = change.value.ad_id;
      const createdTime = change.value.created_time;

      // Fetch lead details from Meta
      const leadData = fetchLeadDetails(leadId);
      if (!leadData) continue;

      const row = buildRow(leadData, createdTime, "Meta");
      appendToSheet(row);
    }
    return ContentService.createTextOutput("EVENT_RECEIVED");
  } catch (err) {
    console.error(err);
    return ContentService.createTextOutput("ERROR");
  }
}

function fetchLeadDetails(leadId) {
  const url = `https://graph.facebook.com/v18.0/${leadId}?fields=field_data,form_id,created_time,ad_id&access_token=${META_TOKEN}`;
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  const json = JSON.parse(resp.getContentText());
  if (json.error) {
    console.error("Lead fetch error:", json.error);
    return null;
  }
  return json;
}

function buildRow(lead, createdTime, source) {
  const fields = {};
  for (const f of lead.field_data || []) {
    fields[f.name] = f.values ? f.values[0] : "";
  }

  const timestamp = createdTime ? new Date(createdTime * 1000).toISOString() : new Date().toISOString();

  return [
    timestamp,
    source,
    fields["whats_the_occasion"] || fields["occasion"] || "",
    fields["whats_your_jewellery_budget"] || fields["budget"] || "",
    fields["when_are_you_planning_to_purchase"] || fields["purchase_timeline"] || "",
    fields["email"] || fields["email_address"] || "",
    fields["full_name"] || fields["name"] || "",
    fields["phone_number"] || fields["phone"] || ""
  ];
}

function appendToSheet(row) {
  const ss = SpreadsheetApp.openByUrl("https://docs.google.com/spreadsheets/d/11X4-LGdGnNXCvcRKsyUNRx8-6Sk8bhd4okHwzFcS-WU/edit");
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error("Sheet not found: " + SHEET_NAME);
  sheet.appendRow(row);
}

function setup() {
  // Run once to set the Meta token in script properties
  PropertiesService.getScriptProperties().setProperty("META_TOKEN", "PASTE_PAGE_TOKEN_HERE");
  console.log("Token saved");
}
