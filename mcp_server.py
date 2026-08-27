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

# Broad discovery queries.
# The relevance filter below will remove generic conversations.
SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing platform",
    "event registration",
    "event tickets",
    "event platform",
    "conference ticketing",
    "ticketing software",
]

# Number of results requested for each query.
RESULTS_PER_QUERY = 50

# Maximum amount of content sent to Gemini per signal.
MAX_CONTENT_LENGTH = 1800


# ============================================================
# RELEVANCE KEYWORDS
# ============================================================

# These indicate that someone may actually be involved
# in organising or operating an event.

ORGANISER_KEYWORDS = [
    "organize an event",
    "organise an event",
    "organizing an event",
    "organising an event",
    "organizer",
    "organiser",
    "event organizer",
    "event organiser",
    "event company",
    "event business",
    "conference organizer",
    "conference organiser",
    "conference organizer",
    "conference organiser",
    "festival organizer",
    "festival organiser",
    "meetup organizer",
    "meetup organiser",
    "event manager",
    "event management",
    "run events",
    "running events",
    "host events",
    "hosting events",
    "event host",
    "event production",
    "event production company",
    "event agency",
    "event agency",
    "our event",
    "my event",
    "we run",
    "we organize",
    "we organise",
    "i organize",
    "i organise",
    "i run events",
    "we run events",
]


# These indicate an actual ticketing/platform discussion.

TICKETING_KEYWORDS = [
    "eventbrite",
    "ticketing",
    "ticketing platform",
    "ticketing software",
    "ticket platform",
    "ticket platform",
    "event registration",
    "registration platform",
    "registration software",
    "event tickets",
    "tickets",
    "checkout",
    "ticket sales",
    "ticket fees",
    "ticket fee",
    "booking platform",
    "event platform",
    "attendee management",
    "attendee data",
    "event management platform",
]


# These indicate business pain, buying intent, or
# evaluation of alternatives.

BUYING_SIGNAL_KEYWORDS = [
    "looking for",
    "looking to",
    "alternative",
    "alternatives",
    "switch",
    "switching",
    "replace",
    "replacing",
    "move away",
    "moving away",
    "migrate",
    "migration",
    "compare",
    "comparing",
    "recommend",
    "recommendation",
    "recommendations",
    "better than",
    "instead of",
    "problem with",
    "problems with",
    "issue with",
    "issues with",
    "frustrated",
    "frustrating",
    "expensive",
    "fees",
    "fee",
    "commission",
    "pricing",
    "cost",
    "checkout problem",
    "checkout problems",
    "api limitation",
    "api limitations",
    "integration problem",
    "integration problems",
    "customer support",
    "poor support",
    "bad support",
    "white label",
    "white-label",
    "branding",
    "own domain",
    "own website",
    "own checkout",
    "attendee data",
    "data ownership",
    "payout",
    "payouts",
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clean_html(raw_html: str) -> str:
    """
    Remove HTML tags and common HTML entities.
    """

    if not raw_html:
        return ""

    cleanr = re.compile(r"<.*?>")

    text = re.sub(
        cleanr,
        "",
        raw_html,
    )

    replacements = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&#x27;": "'",
        "&#39;": "'",
        "&quot;": '"',
        "&nbsp;": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text.strip()


def normalize_text(text: str) -> str:
    """
    Normalize text for keyword matching.
    """

    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def contains_any(
    text: str,
    keywords: list[str],
) -> bool:
    """
    Return True if the text contains at least one
    keyword from the supplied list.
    """

    normalized = normalize_text(text)

    return any(
        keyword.lower() in normalized
        for keyword in keywords
    )


def relevance_score(content: str) -> int:
    """
    Calculate a simple deterministic relevance score.

    This does NOT replace Gemini qualification.

    It only removes obviously irrelevant conversations
    before sending them to Gemini.
    """

    text = normalize_text(content)

    organiser_matches = sum(
        1
        for keyword in ORGANISER_KEYWORDS
        if keyword.lower() in text
    )

    ticketing_matches = sum(
        1
        for keyword in TICKETING_KEYWORDS
        if keyword.lower() in text
    )

    buying_matches = sum(
        1
        for keyword in BUYING_SIGNAL_KEYWORDS
        if keyword.lower() in text
    )

    score = 0

    # Organiser evidence.
    score += min(
        organiser_matches * 3,
        9,
    )

    # Ticketing evidence.
    score += min(
        ticketing_matches * 3,
        9,
    )

    # Buying signal.
    score += min(
        buying_matches * 4,
        12,
    )

    return score


def is_relevant_signal(content: str) -> bool:
    """
    Determine whether a Hacker News comment has enough
    evidence to be worth sending to Gemini.

    Requirements:

    A) Must contain ticketing/event-platform evidence.

    AND

    B) Must contain organiser/business evidence OR
       meaningful buying/pain evidence.
    """

    if not content:
        return False

    text = normalize_text(content)

    has_ticketing = contains_any(
        text,
        TICKETING_KEYWORDS,
    )

    if not has_ticketing:
        return False

    has_organiser = contains_any(
        text,
        ORGANISER_KEYWORDS,
    )

    has_buying_signal = contains_any(
        text,
        BUYING_SIGNAL_KEYWORDS,
    )

    score = relevance_score(text)

    # Strong organiser + ticketing signal.
    if has_organiser and score >= 6:
        return True

    # Strong buying/pain + ticketing signal.
    if has_buying_signal and score >= 7:
        return True

    return False


# ============================================================
# GOOGLE AUTHENTICATION
# ============================================================

def get_google_client():
    """
    Authenticate with Google using the service account.
    """

    credentials = os.environ.get(
        "GCP_CREDENTIALS"
    )

    if not credentials:
        raise RuntimeError(
            "GCP_CREDENTIALS environment variable is missing."
        )

    try:
        creds_dict = json.loads(
            credentials
        )
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "GCP_CREDENTIALS is not valid JSON."
        ) from error

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes,
    )

    return gspread.authorize(
        creds
    )


# ============================================================
# MCP TOOL 1
# SEARCH HACKER NEWS
# ============================================================

@mcp.tool
def search_demand_signals() -> list[dict]:
    """
    Search Hacker News for potential B2B demand signals
    related to event ticketing and event platforms.

    The tool performs:

    1. Broad Hacker News discovery.
    2. Deduplication.
    3. Deterministic relevance filtering.
    4. Returns only stronger signals to the AI agent.
    """

    print(
        "MCP: Starting Hacker News signal collection..."
    )

    all_results = {}

    raw_count = 0

    filtered_count = 0

    # --------------------------------------------------------
    # SEARCH EACH QUERY
    # --------------------------------------------------------

    for query in SEARCH_QUERIES:

        print(
            f"MCP: Searching for: {query}"
        )

        try:

            params = {
                "query": query,
                "tags": "comment",
                "hitsPerPage": RESULTS_PER_QUERY,
            }

            response = requests.get(
                HN_SEARCH_URL,
                params=params,
                timeout=20,
            )

            response.raise_for_status()

            data = response.json()

            hits = data.get(
                "hits",
                [],
            )

            raw_count += len(hits)

            for item in hits:

                object_id = item.get(
                    "objectID"
                )

                if not object_id:
                    continue

                object_id = str(
                    object_id
                )

                comment_text = clean_html(
                    item.get(
                        "comment_text",
                        "",
                    )
                )

                if not comment_text:
                    continue

                # ------------------------------------------------
                # FILTER IRRELEVANT SIGNALS
                # ------------------------------------------------

                if not is_relevant_signal(
                    comment_text
                ):

                    filtered_count += 1

                    continue

                all_results[
                    object_id
                ] = {
                    "source": "Hacker News",
                    "source_id": object_id,
                    "author": item.get(
                        "author",
                        "Unknown",
                    ),
                    "content": comment_text[
                        :MAX_CONTENT_LENGTH
                    ],
                    "url": (
                        "https://news.ycombinator.com/"
                        f"item?id={object_id}"
                    ),
                    "created_at": item.get(
                        "created_at",
                        "",
                    ),
                    "search_query": query,
                    "relevance_score": relevance_score(
                        comment_text
                    ),
                }

        except requests.RequestException as error:

            print(
                "MCP: Hacker News request failed "
                f"for '{query}': {error}"
            )

        except Exception as error:

            print(
                "MCP: Unexpected error for "
                f"'{query}': {error}"
            )

    results = list(
        all_results.values()
    )

    # --------------------------------------------------------
    # SORT BY RELEVANCE
    # --------------------------------------------------------

    results.sort(
        key=lambda item: item.get(
            "relevance_score",
            0,
        ),
        reverse=True,
    )

    print(
        "MCP: Raw Hacker News results: "
        f"{raw_count}"
    )

    print(
        "MCP: Removed irrelevant signals: "
        f"{filtered_count}"
    )

    print(
        "MCP: Final unique relevant signals: "
        f"{len(results)}"
    )

    # --------------------------------------------------------
    # SAMPLE SIGNALS
    # --------------------------------------------------------

    if results:

        print(
            "\n========== TOP RELEVANT SIGNALS =========="
        )

        for index, signal in enumerate(
            results[:5],
            start=1,
        ):

            print(
                f"\n--- Signal {index} ---"
            )

            print(
                f"Source: {signal.get('source')}"
            )

            print(
                f"Author: {signal.get('author')}"
            )

            print(
                f"Relevance: "
                f"{signal.get('relevance_score')}"
            )

            print(
                f"URL: {signal.get('url')}"
            )

            print(
                f"Content: "
                f"{signal.get('content', '')[:500]}"
            )

        print(
            "\n===========================================\n"
        )

    return results


# ============================================================
# MCP TOOL 2
# SAVE QUALIFIED LEADS TO GOOGLE SHEETS
# ============================================================

@mcp.tool
def save_qualified_leads(
    leads: list[dict],
) -> dict:
    """
    Save qualified opportunities into Google Sheets.

    Automatically creates the Qualified Leads worksheet
    and prevents duplicate source IDs.
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

        sheet_id = os.environ.get(
            "SHEET_ID"
        )

        if not sheet_id:

            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(
            sheet_id
        )

        # ----------------------------------------------------
        # GET OR CREATE WORKSHEET
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

        # ----------------------------------------------------
        # HEADERS
        # ----------------------------------------------------

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

        existing_values = (
            worksheet.get_all_values()
        )

        # ----------------------------------------------------
        # CREATE HEADER
        # ----------------------------------------------------

        if not existing_values:

            worksheet.append_row(
                headers
            )

            existing_source_ids = set()

        else:

            existing_source_ids = set()

            for row in existing_values[1:]:

                if len(row) > 2 and row[2]:

                    existing_source_ids.add(
                        str(row[2]).strip()
                    )

        # ----------------------------------------------------
        # PREPARE ROWS
        # ----------------------------------------------------

        rows_to_add = []

        duplicates = 0

        detected_at = datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

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

            existing_source_ids.add(
                source_id
            )

        # ----------------------------------------------------
        # WRITE ROWS
        # ----------------------------------------------------

        if rows_to_add:

            worksheet.append_rows(
                rows_to_add,
                value_input_option="USER_ENTERED",
            )

        print(
            f"MCP: Added "
            f"{len(rows_to_add)} leads."
        )

        print(
            f"MCP: Skipped "
            f"{duplicates} duplicates."
        )

        return {
            "success": True,
            "added": len(rows_to_add),
            "duplicates": duplicates,
        }

    except Exception as error:

        print(
            "MCP: Google Sheets error: "
            f"{error}"
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
    Log every autonomous agent execution
    into the Run Log worksheet.
    """

    try:

        sheet_id = os.environ.get(
            "SHEET_ID"
        )

        if not sheet_id:

            raise RuntimeError(
                "SHEET_ID environment variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(
            sheet_id
        )

        # ----------------------------------------------------
        # GET OR CREATE RUN LOG
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
        # CREATE HEADER
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
        # WRITE LOG
        # ----------------------------------------------------

        worksheet.append_row([
            datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            ),

            str(
                signals_found
            ),

            str(
                qualified_leads
            ),

            str(
                leads_added
            ),

            str(
                duplicates
            ),

            status,

            str(
                error
            )[:500],
        ])

        print(
            "MCP: Run successfully logged."
        )

        return True

    except Exception as error:

        print(
            "MCP: Could not log run: "
            f"{error}"
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


