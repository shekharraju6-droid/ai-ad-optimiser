/**
 * Meta Campaign Lead Poller for Google Sheets (Crash Club)
 * Runs every 5 minutes, pulls individual lead details from all forms of a Meta Page,
 * and appends them to the sheet tab "JUNE | JULY 2026 - Goa Leads" with automatic deduplication.
 * 
 * Setup:
 * 1. Open the target Google Sheet: https://docs.google.com/spreadsheets/d/11X4-LGdGnNXCvcRKsyUNRx8-6Sk8bhd4okHwzFcS-WU/edit
 * 2. Click Extensions -> Apps Script.
 * 3. Replace all default code with the contents of this file.
 * 4. Click the Settings gear icon (Project Settings) on the left.
 * 5. Scroll down to "Script Properties" and add:
 *    - META_ACCESS_TOKEN: <your never-expiring Page Access Token>
 *    - PAGE_ID: <your Facebook Page ID>
 * 6. In the function dropdown at the top of the editor, select "setup" and click "Run". This schedules the poller.
 * 7. (Optional) Run "pollMetaLeads" manually to test the script.
 */

const SHEET_URL = "https://docs.google.com/spreadsheets/d/11X4-LGdGnNXCvcRKsyUNRx8-6Sk8bhd4okHwzFcS-WU/edit";
const SHEET_NAME = "JUNE | JULY 2026 - Goa Leads";
const API_VERSION = "v18.0";

/**
 * Creates the time-driven trigger to run the poller every 5 minutes.
 * Run this function once during initial setup.
 */
function setup() {
  // Clear any existing triggers for pollMetaLeads to avoid duplicates
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "pollMetaLeads") {
      ScriptApp.deleteTrigger(t);
    }
  });

  // Create new trigger for every 5 minutes
  ScriptApp.newTrigger("pollMetaLeads")
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log("Trigger successfully created to run pollMetaLeads every 5 minutes.");
}

/**
 * Core poller function. Fetches lead forms, retrieves leads, filters duplicates,
 * and appends new leads to the Google Sheet.
 */
function pollMetaLeads() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty("META_ACCESS_TOKEN");
  const pageId = props.getProperty("PAGE_ID");

  if (!token) {
    Logger.log("ERROR: META_ACCESS_TOKEN script property is not set.");
    return;
  }
  if (!pageId) {
    Logger.log("ERROR: PAGE_ID script property is not set.");
    return;
  }

  // Retrieve the timestamp (in ms) of the last lead we processed.
  // If not set, default to 24 hours ago to avoid fetching historical clutter.
  let lastProcessedTime = parseInt(props.getProperty("LAST_PROCESSED_TIME") || "0", 10);
  if (lastProcessedTime === 0) {
    lastProcessedTime = Date.now() - (24 * 60 * 60 * 1000);
  }

  try {
    const ss = SpreadsheetApp.openByUrl(SHEET_URL);
    const sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) {
      Logger.log("ERROR: Sheet tab '" + SHEET_NAME + "' not found in spreadsheet.");
      return;
    }

    // 1. Scan the last 200 rows of the sheet to prevent duplicates if the script is run manually
    const existingLeads = new Set();
    const lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      const startRow = Math.max(2, lastRow - 200);
      const numRows = lastRow - startRow + 1;
      const data = sheet.getRange(startRow, 1, numRows, 8).getValues();
      for (const row of data) {
        // Unique composite key: formatted timestamp + email + phone
        const key = `${row[0]}|${row[5]}|${row[7]}`;
        existingLeads.add(key);
      }
    }

    // 2. Fetch all lead forms for the Facebook Page
    const formsUrl = `https://graph.facebook.com/${API_VERSION}/${pageId}/leadgen_forms?fields=id,name,status&limit=50&access_token=${encodeURIComponent(token)}`;
    const formsResponse = UrlFetchApp.fetch(formsUrl, { muteHttpExceptions: true });
    const formsResult = JSON.parse(formsResponse.getContentText());

    if (formsResult.error) {
      Logger.log("Meta API Error (fetching forms): " + JSON.stringify(formsResult.error));
      return;
    }

    const forms = formsResult.data || [];
    let newLeadsCount = 0;
    let maxTimeSeen = lastProcessedTime;

    // 3. For each lead form, retrieve leads
    for (const form of forms) {
      const leadsUrl = `https://graph.facebook.com/${API_VERSION}/${form.id}/leads?fields=id,created_time,field_data&limit=50&access_token=${encodeURIComponent(token)}`;
      const leadsResponse = UrlFetchApp.fetch(leadsUrl, { muteHttpExceptions: true });
      const leadsResult = JSON.parse(leadsResponse.getContentText());

      if (leadsResult.error) {
        Logger.log(`Meta API Error (fetching leads for form ${form.name}): ` + JSON.stringify(leadsResult.error));
        continue;
      }

      const leads = leadsResult.data || [];
      for (const lead of leads) {
        const leadTimeMs = Date.parse(lead.created_time);
        
        // Filter out leads that are older than our last processed timestamp
        if (leadTimeMs <= lastProcessedTime) {
          continue;
        }

        const row = buildRow(lead, "Meta", form.name);
        const uniqueKey = `${row[0]}|${row[5]}|${row[7]}`; // timestamp|email|phone

        // Double check against existing sheet rows
        if (!existingLeads.has(uniqueKey)) {
          sheet.appendRow(row);
          existingLeads.add(uniqueKey);
          newLeadsCount++;
          
          if (leadTimeMs > maxTimeSeen) {
            maxTimeSeen = leadTimeMs;
          }
        }
      }
    }

    // 4. Update the last processed timestamp script property
    if (maxTimeSeen > lastProcessedTime) {
      props.setProperty("LAST_PROCESSED_TIME", maxTimeSeen.toString());
    }

    Logger.log(`Successfully completed polling. Appended ${newLeadsCount} new leads.`);

  } catch (e) {
    Logger.log("Execution error: " + e.message);
  }
}

/**
 * Parses Meta lead fields and maps them to the Google Sheet columns structure:
 * [Lead Created, Source, Occasion, Budget, Purchase Timeline, Email ID, Full Name, Phone Number]
 */
function buildRow(lead, source, formName) {
  const fields = {};
  for (const f of lead.field_data || []) {
    const name = (f.name || "").toLowerCase();
    const value = f.values ? f.values[0] : "";
    fields[name] = value;
  }

  // Search helper for standard field names and common questionnaire keywords
  const findValue = (keys) => {
    for (const key of keys) {
      if (fields[key] !== undefined) return fields[key];
    }
    // Partial substring match helper for customized client questions
    for (const name in fields) {
      for (const key of keys) {
        if (name.indexOf(key) !== -1) return fields[name];
      }
    }
    return "";
  };

  const occasion = findValue(["occasion", "event"]);
  const budget = findValue(["budget", "spend", "value"]);
  const purchaseTimeline = findValue(["purchase_timeline", "planning_to_purchase", "timeline", "when"]);
  const email = findValue(["email", "mail"]);
  const fullName = findValue(["full_name", "name", "first_name", "last_name"]);
  const phone = findValue(["phone_number", "phone", "contact", "mobile"]);

  // Format the creation date to Asia/Kolkata timezone
  const formattedTimestamp = lead.created_time 
    ? Utilities.formatDate(new Date(lead.created_time), "Asia/Kolkata", "yyyy-MM-dd HH:mm:ss")
    : Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm:ss");

  return [
    formattedTimestamp,
    source, // e.g. "Meta"
    occasion,
    budget,
    purchaseTimeline,
    email,
    fullName,
    phone
  ];
}
