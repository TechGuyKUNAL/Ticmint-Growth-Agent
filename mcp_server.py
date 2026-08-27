import os
import json
import re
from datetime import datetime, timezone, timedelta

import requests
import gspread
from google.oauth2.service_account import Credentials
from fastmcp import FastMCP


mcp = FastMCP("TicmintDemandCapture")


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"

SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing",
    "ticket tickets",
    "event tickets",
    "event registration",
    "conference tickets",
    "event platform",
]


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_html(raw_html: str) -> str:
    """Remove HTML tags from Hacker News comments."""
    if not raw_html:
        return ""

    cleanr = re.compile(r"<.*?>")
    text = re.sub(cleanr, "", raw_html)

    # Basic HTML entity cleanup
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x27;", "'")
        .replace("&quot;", '"')
    )

    return text.strip()


def get_google_client():
    """Create an authenticated Google Sheets client."""
    credentials = os.environ.get("GCP_CREDENTIALS")

    if not credentials:
        raise RuntimeError("GCP_CREDENTIALS environment variable is missing.")

    creds_dict = json.loads(credentials)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes,
    )

    return gspread.authorize(creds)


# ---------------------------------------------------------
# MCP TOOL 1: Search public demand signals
# ---------------------------------------------------------

@mcp.tool
def search_demand_signals() -> list[dict]:
    """
    Searches publicly available Hacker News discussions for
    event-ticketing demand and pain signals.

    Returns normalized conversation records.
    """

    print("MCP: Searching Hacker News demand signals...")

    all_results = {}
    "numericFilters": f"created_at_i>{cutoff_timestamp}",

    for query in SEARCH_QUERIES:
        try:
            params = {
                "query": query,
                "tags": "comment",
                "hitsPerPage": 20,
                "numericFilters": f"created_at_i>{cutoff_timestamp}",
            }

            response = requests.get(
                HN_SEARCH_URL,
                params=params,
                timeout=15,
            )

            response.raise_for_status()

            data = response.json()

            for item in data.get("hits", []):
                object_id = item.get("objectID")

                if not object_id:
                    continue

                comment_text = clean_html(
                    item.get("comment_text", "")
                )

                if not comment_text:
                    continue

                # Deduplicate by Hacker News object ID
                all_results[object_id] = {
                    "source": "Hacker News",
                    "source_id": str(object_id),
                    "author": item.get("author") or "Unknown",
                    "content": comment_text[:1000],
                    "url": (
                        "https://news.ycombinator.com/"
                        f"item?id={object_id}"
                    ),
                    "created_at": item.get("created_at", ""),
                    "search_query": query,
                }

        except requests.RequestException as exc:
            print(
                f"MCP: Hacker News request failed for "
                f"'{query}': {exc}"
            )

        except Exception as exc:
            print(
                f"MCP: Unexpected error for "
                f"'{query}': {exc}"
            )

    results = list(all_results.values())

    print(
        f"MCP: Found {len(results)} unique public "
        f"conversation signals."
    )

    return results


# ---------------------------------------------------------
# MCP TOOL 2: Save qualified leads
# ---------------------------------------------------------

@mcp.tool
def save_qualified_leads(leads: list[dict]) -> dict:
    """
    Saves qualified demand signals to Google Sheets.

    Automatically creates the required sheets and prevents
    duplicate source IDs from being inserted.
    """

    if not leads:
        return {
            "success": True,
            "added": 0,
            "duplicates": 0,
        }

    print(
        f"MCP: Saving {len(leads)} qualified opportunities..."
    )

    try:
        sheet_id = os.environ.get("SHEET_ID")

        if not sheet_id:
            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()
        spreadsheet = gc.open_by_key(sheet_id)

        # -------------------------------------------------
        # Leads worksheet
        # -------------------------------------------------

        try:
            leads_sheet = spreadsheet.worksheet("Qualified Leads")
        except gspread.WorksheetNotFound:
            leads_sheet = spreadsheet.add_worksheet(
                title="Qualified Leads",
                rows=1000,
                cols=20,
            )

        headers = [
            "Detected At",
            "Source",
            "Source ID",
            "Author",
            "URL",
            "Current Platform",
            "Event Type",
            "Event Scale",
            "Pain Category",
            "Pain Point",
            "Urgency",
            "Switching Intent",
            "Ticmint Fit",
            "Opportunity Score",
            "Why This Lead",
            "Outreach Draft",
        ]

        existing_values = leads_sheet.get_all_values()

        if not existing_values:
            leads_sheet.append_row(headers)
            existing_source_ids = set()
        else:
            existing_source_ids = {
                row[2]
                for row in existing_values[1:]
                if len(row) > 2 and row[2]
            }

        rows_to_add = []
        duplicates = 0

        detected_at = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        for lead in leads:
            source_id = str(
                lead.get("source_id", "")
            ).strip()

            if not source_id:
                continue

            if source_id in existing_source_ids:
                duplicates += 1
                continue

            rows_to_add.append([
                detected_at,
                lead.get("source", "Hacker News"),
                source_id,
                lead.get("author", ""),
                lead.get("url", ""),
                lead.get("current_platform", ""),
                lead.get("event_type", ""),
                lead.get("event_scale", ""),
                lead.get("pain_category", ""),
                lead.get("pain_point", ""),
                lead.get("urgency", ""),
                lead.get("switching_intent", ""),
                lead.get("ticmint_fit", ""),
                str(lead.get("opportunity_score", "")),
                lead.get("why_this_lead", ""),
                lead.get("outreach_draft", ""),
            ])

            existing_source_ids.add(source_id)

        if rows_to_add:
            leads_sheet.append_rows(
                rows_to_add,
                value_input_option="USER_ENTERED",
            )

        print(
            f"MCP: Added {len(rows_to_add)} leads. "
            f"Skipped {duplicates} duplicates."
        )

        return {
            "success": True,
            "added": len(rows_to_add),
            "duplicates": duplicates,
        }

    except Exception as exc:
        print(f"MCP: Google Sheets error: {exc}")

        return {
            "success": False,
            "added": 0,
            "duplicates": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------
# MCP TOOL 3: Log every agent run
# ---------------------------------------------------------

@mcp.tool
def log_agent_run(
    signals_found: int,
    new_signals: int,
    qualified_leads: int,
    duplicates: int,
    status: str,
    error: str = "",
) -> bool:
    """
    Logs every autonomous agent run to Google Sheets.
    """

    try:
        sheet_id = os.environ.get("SHEET_ID")

        if not sheet_id:
            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()
        spreadsheet = gc.open_by_key(sheet_id)

        try:
            run_sheet = spreadsheet.worksheet("Run Log")
        except gspread.WorksheetNotFound:
            run_sheet = spreadsheet.add_worksheet(
                title="Run Log",
                rows=1000,
                cols=10,
            )

        existing = run_sheet.get_all_values()

        if not existing:
            run_sheet.append_row([
                "Run Time",
                "Signals Found",
                "New Signals",
                "Qualified Leads",
                "Duplicates",
                "Status",
                "Error",
            ])

        run_sheet.append_row([
            datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),
            str(signals_found),
            str(new_signals),
            str(qualified_leads),
            str(duplicates),
            status,
            error[:500],
        ])

        return True

    except Exception as exc:
        print(f"MCP: Failed to log run: {exc}")
        return False


# ---------------------------------------------------------
# Run MCP server directly
# ---------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
