import os
import json
import re
from datetime import datetime, timezone

import requests
import gspread
from google.oauth2.service_account import Credentials
from fastmcp import FastMCP


# ============================================================
# TICMINT CUSTOM MCP SERVER
# ============================================================

mcp = FastMCP("TicmintDemandCapture")


# ============================================================
# CONFIGURATION
# ============================================================

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"

SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing",
    "event tickets",
    "event registration",
    "conference tickets",
    "event platform",
    "ticketing platform",
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clean_html(raw_html: str) -> str:
    """Remove HTML tags and basic HTML entities."""

    if not raw_html:
        return ""

    cleanr = re.compile(r"<.*?>")

    text = re.sub(cleanr, "", raw_html)

    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x27;", "'")
        .replace("&quot;", '"')
    )

    return text.strip()


def get_google_client():
    """Authenticate with Google using the service account."""

    credentials = os.environ.get("GCP_CREDENTIALS")

    if not credentials:
        raise RuntimeError(
            "GCP_CREDENTIALS environment variable is missing."
        )

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


# ============================================================
# MCP TOOL 1
# SEARCH HACKER NEWS
# ============================================================

@mcp.tool
def search_demand_signals() -> list[dict]:
    """
    Search Hacker News for public conversations related to
    event ticketing, event platforms and Eventbrite.

    This is the custom MCP data acquisition tool.
    """

    print("MCP: Starting Hacker News signal collection...")

    all_results = {}

    for query in SEARCH_QUERIES:

        print(f"MCP: Searching for: {query}")

        try:

            params = {
                "query": query,
                "tags": "comment",
                "hitsPerPage": 20,
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

                all_results[str(object_id)] = {
                    "source": "Hacker News",
                    "source_id": str(object_id),
                    "author": item.get(
                        "author",
                        "Unknown",
                    ),
                    "content": comment_text[:1000],
                    "url": (
                        "https://news.ycombinator.com/"
                        f"item?id={object_id}"
                    ),
                    "created_at": item.get(
                        "created_at",
                        "",
                    ),
                    "search_query": query,
                }

        except requests.RequestException as error:

            print(
                f"MCP: Hacker News request failed "
                f"for '{query}': {error}"
            )

        except Exception as error:

            print(
                f"MCP: Unexpected error for "
                f"'{query}': {error}"
            )

    results = list(all_results.values())

    print(
        f"MCP: Collection complete. "
        f"Found {len(results)} unique signals."
    )

    return results


# ============================================================
# MCP TOOL 2
# SAVE QUALIFIED LEADS TO GOOGLE SHEETS
# ============================================================

@mcp.tool
def save_qualified_leads(leads: list[dict]) -> dict:
    """
    Save qualified opportunities into Google Sheets.

    Automatically creates the Qualified Leads worksheet
    and prevents duplicate Hacker News source IDs.
    """

    if not leads:

        return {
            "success": True,
            "added": 0,
            "duplicates": 0,
        }

    print(
        f"MCP: Preparing to save "
        f"{len(leads)} qualified leads."
    )

    try:

        sheet_id = os.environ.get("SHEET_ID")

        if not sheet_id:

            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(sheet_id)

        # ----------------------------------------------------
        # Get or create Qualified Leads sheet
        # ----------------------------------------------------

        try:

            worksheet = spreadsheet.worksheet(
                "Qualified Leads"
            )

        except gspread.WorksheetNotFound:

            worksheet = spreadsheet.add_worksheet(
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

        existing_values = worksheet.get_all_values()

        # ----------------------------------------------------
        # Create header if sheet is empty
        # ----------------------------------------------------

        if not existing_values:

            worksheet.append_row(headers)

            existing_source_ids = set()

        else:

            existing_source_ids = set()

            for row in existing_values[1:]:

                if len(row) > 2 and row[2]:

                    existing_source_ids.add(
                        str(row[2])
                    )

        rows_to_add = []

        duplicates = 0

        detected_at = datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        # ----------------------------------------------------
        # Deduplicate
        # ----------------------------------------------------

        for lead in leads:

            source_id = str(
                lead.get(
                    "source_id",
                    "",
                )
            ).strip()

            if not source_id:

                continue

            if source_id in existing_source_ids:

                duplicates += 1

                continue

            rows_to_add.append([
                detected_at,
                lead.get(
                    "source",
                    "Hacker News",
                ),
                source_id,
                lead.get(
                    "author",
                    "",
                ),
                lead.get(
                    "url",
                    "",
                ),
                lead.get(
                    "current_platform",
                    "Unknown",
                ),
                lead.get(
                    "event_type",
                    "Unknown",
                ),
                lead.get(
                    "event_scale",
                    "Unknown",
                ),
                lead.get(
                    "pain_category",
                    "Unknown",
                ),
                lead.get(
                    "pain_point",
                    "",
                ),
                lead.get(
                    "urgency",
                    "Unknown",
                ),
                lead.get(
                    "switching_intent",
                    "Unknown",
                ),
                lead.get(
                    "ticmint_fit",
                    "Unknown",
                ),
                str(
                    lead.get(
                        "opportunity_score",
                        "",
                    )
                ),
                lead.get(
                    "why_this_lead",
                    "",
                ),
                lead.get(
                    "outreach_draft",
                    "",
                ),
            ])

            existing_source_ids.add(source_id)

        # ----------------------------------------------------
        # Write new rows
        # ----------------------------------------------------

        if rows_to_add:

            worksheet.append_rows(
                rows_to_add,
                value_input_option="USER_ENTERED",
            )

        print(
            f"MCP: Added {len(rows_to_add)} leads."
        )

        print(
            f"MCP: Skipped {duplicates} duplicates."
        )

        return {
            "success": True,
            "added": len(rows_to_add),
            "duplicates": duplicates,
        }

    except Exception as error:

        print(
            f"MCP: Google Sheets error: {error}"
        )

        return {
            "success": False,
            "added": 0,
            "duplicates": 0,
            "error": str(error),
        }


# ============================================================
# MCP TOOL 3
# LOG EVERY RUN
# ============================================================

@mcp.tool
def log_agent_run(
    signals_found: int,
    qualified_leads: int,
    leads_added: int,
    duplicates: int,
    status: str,
    error: str = "",
) -> bool:
    """
    Log every autonomous agent execution into a Run Log sheet.
    """

    try:

        sheet_id = os.environ.get("SHEET_ID")

        if not sheet_id:

            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(sheet_id)

        # ----------------------------------------------------
        # Get or create Run Log sheet
        # ----------------------------------------------------

        try:

            worksheet = spreadsheet.worksheet(
                "Run Log"
            )

        except gspread.WorksheetNotFound:

            worksheet = spreadsheet.add_worksheet(
                title="Run Log",
                rows=1000,
                cols=10,
            )

        # ----------------------------------------------------
        # Create headers
        # ----------------------------------------------------

        if not worksheet.get_all_values():

            worksheet.append_row([
                "Run Time",
                "Signals Found",
                "Qualified Leads",
                "Leads Added",
                "Duplicates",
                "Status",
                "Error",
            ])

        # ----------------------------------------------------
        # Add run
        # ----------------------------------------------------

        worksheet.append_row([
            datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),
            str(signals_found),
            str(qualified_leads),
            str(leads_added),
            str(duplicates),
            status,
            error[:500],
        ])

        print(
            "MCP: Run successfully logged."
        )

        return True

    except Exception as error:

        print(
            f"MCP: Could not log run: {error}"
        )

        return False


# ============================================================
# START MCP SERVER
# ============================================================

if __name__ == "__main__":

    print(
        "Starting Ticmint Custom MCP Server..."
    )

    mcp.run()
