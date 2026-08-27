import os
import json
import re
import time
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

# ------------------------------------------------------------
# Hacker News
# ------------------------------------------------------------

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


# ------------------------------------------------------------
# Stack Exchange / Stack Overflow
# ------------------------------------------------------------

STACK_EXCHANGE_SEARCH_URL = (
    "https://api.stackexchange.com/2.3/search/advanced"
)


# ------------------------------------------------------------
# GitHub
# ------------------------------------------------------------

GITHUB_SEARCH_URL = (
    "https://api.github.com/search/issues"
)


# ------------------------------------------------------------
# DEV Community
# ------------------------------------------------------------

DEV_SEARCH_URL = (
    "https://dev.to/api/articles/search"
)


# ------------------------------------------------------------
# Lobsters
# ------------------------------------------------------------

LOBSTERS_NEWEST_URL = (
    "https://lobste.rs/newest.json"
)

LOBSTERS_HOTTEST_URL = (
    "https://lobste.rs/hottest.json"
)


# ============================================================
# SEARCH QUERIES
# ============================================================

HN_SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing",
    "event tickets",
    "event registration",
    "conference tickets",
    "event platform",
    "ticketing platform",
]


STACK_SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing",
    "event registration",
    "event platform",
]


DEV_SEARCH_QUERIES = [
    "Eventbrite",
    "ticketing",
    "event registration",
]


# ============================================================
# COMMON KEYWORDS
# ============================================================

EVENT_KEYWORDS = [
    "eventbrite",
    "ticketing",
    "ticket",
    "tickets",
    "event registration",
    "registration platform",
    "event platform",
    "event management",
    "conference",
    "festival",
    "event organizer",
    "event organiser",
    "event organizer",
    "event organiser",
]


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Ticmint-Demand-Capture-Agent/1.0 "
            "(public demand research)"
        ),
        "Accept": "application/json",
    }
)


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
        str(raw_html),
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

        text = text.replace(
            old,
            new,
        )

    return text.strip()


def contains_relevant_keyword(text: str) -> bool:
    """
    Check whether text contains at least one
    Ticmint-relevant keyword.
    """

    if not text:
        return False

    lowered = text.lower()

    return any(
        keyword in lowered
        for keyword in EVENT_KEYWORDS
    )


def safe_request(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 20,
    retries: int = 2,
):
    """
    Make a resilient HTTP GET request.

    Temporary 429/500/502/503/504 errors are retried.
    A source failure is allowed to return None so that
    other sources can continue running.
    """

    for attempt in range(retries + 1):

        try:

            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
            )

            # ------------------------------------------------
            # Successful response
            # ------------------------------------------------

            if response.status_code == 200:

                return response

            # ------------------------------------------------
            # Temporary errors
            # ------------------------------------------------

            if response.status_code in {
                429,
                500,
                502,
                503,
                504,
            }:

                if attempt < retries:

                    wait_time = (
                        2 ** attempt
                    )

                    print(
                        f"Temporary HTTP "
                        f"{response.status_code} "
                        f"from {url}. "
                        f"Retrying in "
                        f"{wait_time}s..."
                    )

                    time.sleep(
                        wait_time
                    )

                    continue

                print(
                    f"HTTP {response.status_code} "
                    f"after retries: {url}"
                )

                return None

            # ------------------------------------------------
            # Permanent / other error
            # ------------------------------------------------

            print(
                f"HTTP {response.status_code} "
                f"from {url}"
            )

            return None

        except requests.RequestException as error:

            if attempt < retries:

                wait_time = (
                    2 ** attempt
                )

                print(
                    f"Request error for {url}: "
                    f"{error}. "
                    f"Retrying in "
                    f"{wait_time}s..."
                )

                time.sleep(
                    wait_time
                )

                continue

            print(
                f"Request failed after retries: "
                f"{url}: {error}"
            )

            return None

        except Exception as error:

            print(
                f"Unexpected HTTP error "
                f"for {url}: {error}"
            )

            return None

    return None


def normalize_signal(
    source: str,
    source_id: str,
    author: str,
    content: str,
    url: str,
    created_at: str,
    search_query: str,
) -> dict | None:
    """
    Convert every source into the same signal format.
    """

    content = clean_html(
        content
    ).strip()

    if not content:

        return None

    return {
        "source": source,
        "source_id": str(
            source_id
        ),
        "author": author or "Unknown",
        "content": content[:2000],
        "url": url or "",
        "created_at": created_at or "",
        "search_query": search_query or "",
    }


# ============================================================
# SOURCE 1
# HACKER NEWS
# ============================================================

def search_hacker_news() -> list[dict]:
    """
    Collect relevant public Hacker News comments.
    """

    print(
        "\nMCP: Starting Hacker News collection..."
    )

    all_results = {}

    for query in HN_SEARCH_QUERIES:

        print(
            f"MCP: Hacker News -> {query}"
        )

        params = {
            "query": query,
            "tags": "comment",
            "hitsPerPage": 20,
        }

        response = safe_request(
            HN_SEARCH_URL,
            params=params,
            timeout=15,
        )

        if response is None:

            print(
                f"MCP: Skipping Hacker News "
                f"query: {query}"
            )

            continue

        try:

            data = response.json()

            for item in data.get(
                "hits",
                [],
            ):

                object_id = item.get(
                    "objectID"
                )

                if not object_id:

                    continue

                comment_text = clean_html(
                    item.get(
                        "comment_text",
                        "",
                    )
                )

                if not comment_text:

                    continue

                signal = normalize_signal(
                    source="Hacker News",
                    source_id=str(
                        object_id
                    ),
                    author=item.get(
                        "author",
                        "Unknown",
                    ),
                    content=comment_text,
                    url=(
                        "https://news.ycombinator.com/"
                        f"item?id={object_id}"
                    ),
                    created_at=item.get(
                        "created_at",
                        "",
                    ),
                    search_query=query,
                )

                if signal:

                    all_results[
                        str(object_id)
                    ] = signal

        except Exception as error:

            print(
                f"MCP: Hacker News parsing "
                f"error for '{query}': "
                f"{error}"
            )

    results = list(
        all_results.values()
    )

    print(
        f"MCP: Hacker News collected "
        f"{len(results)} unique signals."
    )

    return results


# ============================================================
# SOURCE 2
# STACK EXCHANGE / STACK OVERFLOW
# ============================================================

def search_stack_exchange() -> list[dict]:
    """
    Search Stack Overflow for public questions related
    to event ticketing and Eventbrite.
    """

    print(
        "\nMCP: Starting Stack Overflow collection..."
    )

    all_results = {}

    for query in STACK_SEARCH_QUERIES:

        print(
            f"MCP: Stack Overflow -> {query}"
        )

        params = {
            "site": "stackoverflow",
            "q": query,
            "sort": "activity",
            "order": "desc",
            "pagesize": 20,
            "page": 1,
        }

        response = safe_request(
            STACK_EXCHANGE_SEARCH_URL,
            params=params,
            timeout=20,
        )

        if response is None:

            print(
                f"MCP: Skipping Stack Overflow "
                f"query: {query}"
            )

            continue

        try:

            data = response.json()

            for item in data.get(
                "items",
                [],
            ):

                question_id = item.get(
                    "question_id"
                )

                if not question_id:

                    continue

                title = clean_html(
                    item.get(
                        "title",
                        "",
                    )
                )

                tags = item.get(
                    "tags",
                    [],
                )

                tag_text = ", ".join(
                    tags
                )

                content = (
                    f"Question: {title}"
                )

                if tag_text:

                    content += (
                        f"\nTags: {tag_text}"
                    )

                link = item.get(
                    "link",
                    "",
                )

                owner = item.get(
                    "owner",
                    {},
                )

                author = owner.get(
                    "display_name",
                    "Unknown",
                )

                created_timestamp = item.get(
                    "creation_date",
                    "",
                )

                created_at = ""

                if created_timestamp:

                    try:

                        created_at = (
                            datetime.fromtimestamp(
                                created_timestamp,
                                timezone.utc,
                            ).isoformat()
                        )

                    except Exception:

                        created_at = ""

                signal = normalize_signal(
                    source="Stack Overflow",
                    source_id=str(
                        question_id
                    ),
                    author=author,
                    content=content,
                    url=link,
                    created_at=created_at,
                    search_query=query,
                )

                if signal:

                    all_results[
                        str(question_id)
                    ] = signal

        except Exception as error:

            print(
                f"MCP: Stack Overflow "
                f"parsing error for "
                f"'{query}': {error}"
            )

    results = list(
        all_results.values()
    )

    print(
        f"MCP: Stack Overflow collected "
        f"{len(results)} unique signals."
    )

    return results


# ============================================================
# SOURCE 3
# GITHUB
# ============================================================

def search_github() -> list[dict]:
    """
    Search public GitHub issues for conversations involving
    Eventbrite, ticketing and event registration.

    Optional:
        GITHUB_TOKEN

    If no token is supplied, GitHub's public unauthenticated
    search API is used.
    """

    print(
        "\nMCP: Starting GitHub collection..."
    )

    results = {}

    github_token = os.environ.get(
        "GITHUB_TOKEN"
    )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    if github_token:

        headers[
            "Authorization"
        ] = f"Bearer {github_token}"

        print(
            "MCP: GitHub authentication enabled."
        )

    else:

        print(
            "MCP: GitHub running without "
            "authentication."
        )

    query = (
        '"Eventbrite" '
        'OR "ticketing" '
        'OR "event registration" '
        'OR "event platform"'
    )

    print(
        f"MCP: GitHub -> {query}"
    )

    params = {
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": 50,
        "page": 1,
    }

    response = safe_request(
        GITHUB_SEARCH_URL,
        params=params,
        headers=headers,
        timeout=20,
    )

    if response is None:

        print(
            "MCP: GitHub collection skipped."
        )

        return []

    try:

        data = response.json()

        for item in data.get(
            "items",
            [],
        ):

            issue_id = item.get(
                "id"
            )

            if not issue_id:

                continue

            title = clean_html(
                item.get(
                    "title",
                    "",
                )
            )

            body = clean_html(
                item.get(
                    "body",
                    "",
                )
            )

            content_parts = []

            if title:

                content_parts.append(
                    f"Issue: {title}"
                )

            if body:

                content_parts.append(
                    f"Description: {body}"
                )

            content = "\n".join(
                content_parts
            )

            if not content:

                continue

            user = item.get(
                "user",
                {},
            )

            author = user.get(
                "login",
                "Unknown",
            )

            signal = normalize_signal(
                source="GitHub",
                source_id=str(
                    issue_id
                ),
                author=author,
                content=content,
                url=item.get(
                    "html_url",
                    "",
                ),
                created_at=item.get(
                    "created_at",
                    "",
                ),
                search_query=query,
            )

            if signal:

                results[
                    str(issue_id)
                ] = signal

    except Exception as error:

        print(
            f"MCP: GitHub parsing error: "
            f"{error}"
        )

    final_results = list(
        results.values()
    )

    print(
        f"MCP: GitHub collected "
        f"{len(final_results)} "
        f"unique signals."
    )

    return final_results


# ============================================================
# SOURCE 4
# DEV COMMUNITY
# ============================================================

def search_dev_community() -> list[dict]:
    """
    Search DEV Community for public articles/discussions
    related to event ticketing and Eventbrite.
    """

    print(
        "\nMCP: Starting DEV Community collection..."
    )

    all_results = {}

    for query in DEV_SEARCH_QUERIES:

        print(
            f"MCP: DEV -> {query}"
        )

        params = {
            "q": query,
            "per_page": 20,
            "page": 1,
        }

        response = safe_request(
            DEV_SEARCH_URL,
            params=params,
            timeout=20,
        )

        if response is None:

            print(
                f"MCP: Skipping DEV query: "
                f"{query}"
            )

            continue

        try:

            data = response.json()

            if not isinstance(
                data,
                list,
            ):

                continue

            for item in data:

                article_id = item.get(
                    "id"
                )

                if not article_id:

                    continue

                title = clean_html(
                    item.get(
                        "title",
                        "",
                    )
                )

                description = clean_html(
                    item.get(
                        "description",
                        "",
                    )
                )

                content_parts = []

                if title:

                    content_parts.append(
                        f"Title: {title}"
                    )

                if description:

                    content_parts.append(
                        f"Description: "
                        f"{description}"
                    )

                content = "\n".join(
                    content_parts
                )

                if not contains_relevant_keyword(
                    content
                ):

                    continue

                user = item.get(
                    "user",
                    {},
                )

                author = user.get(
                    "username",
                    "Unknown",
                )

                url = (
                    item.get(
                        "url"
                    )
                    or item.get(
                        "canonical_url"
                    )
                    or ""
                )

                created_at = (
                    item.get(
                        "published_at"
                    )
                    or item.get(
                        "created_at"
                    )
                    or ""
                )

                signal = normalize_signal(
                    source="DEV Community",
                    source_id=str(
                        article_id
                    ),
                    author=author,
                    content=content,
                    url=url,
                    created_at=created_at,
                    search_query=query,
                )

                if signal:

                    all_results[
                        str(article_id)
                    ] = signal

        except Exception as error:

            print(
                f"MCP: DEV parsing error "
                f"for '{query}': {error}"
            )

    results = list(
        all_results.values()
    )

    print(
        f"MCP: DEV Community collected "
        f"{len(results)} unique signals."
    )

    return results


# ============================================================
# SOURCE 5
# LOBSTERS
# ============================================================

def search_lobsters() -> list[dict]:
    """
    Collect public Lobsters stories from newest and hottest
    JSON feeds and filter them locally for relevant keywords.

    Lobsters exposes JSON representations of public pages,
    so this source does not require an authenticated API key.
    """

    print(
        "\nMCP: Starting Lobsters collection..."
    )

    all_results = {}

    urls = [
        (
            "newest",
            LOBSTERS_NEWEST_URL,
        ),
        (
            "hottest",
            LOBSTERS_HOTTEST_URL,
        ),
    ]

    for feed_name, url in urls:

        print(
            f"MCP: Lobsters -> {feed_name}"
        )

        response = safe_request(
            url,
            timeout=20,
        )

        if response is None:

            print(
                f"MCP: Skipping Lobsters "
                f"{feed_name} feed."
            )

            continue

        try:

            data = response.json()

            if not isinstance(
                data,
                list,
            ):

                continue

            for item in data:

                story_id = item.get(
                    "short_id"
                )

                if not story_id:

                    story_id = item.get(
                        "short_id_url"
                    )

                if not story_id:

                    story_id = item.get(
                        "id"
                    )

                title = clean_html(
                    item.get(
                        "title",
                        "",
                    )
                )

                description = clean_html(
                    item.get(
                        "description",
                        "",
                    )
                )

                tags = item.get(
                    "tags",
                    [],
                )

                tag_text = ", ".join(
                    tags
                ) if isinstance(
                    tags,
                    list,
                ) else str(tags)

                content_parts = []

                if title:

                    content_parts.append(
                        f"Title: {title}"
                    )

                if description:

                    content_parts.append(
                        f"Description: "
                        f"{description}"
                    )

                if tag_text:

                    content_parts.append(
                        f"Tags: {tag_text}"
                    )

                content = "\n".join(
                    content_parts
                )

                if not contains_relevant_keyword(
                    content
                ):

                    continue

                if not story_id:

                    continue

                url_value = item.get(
                    "url",
                    "",
                )

                if not url_value:

                    url_value = (
                        "https://lobste.rs/s/"
                        f"{story_id}"
                    )

                author = item.get(
                    "submitter_user",
                    "Unknown",
                )

                created_at = item.get(
                    "created_at",
                    "",
                )

                signal = normalize_signal(
                    source="Lobsters",
                    source_id=str(
                        story_id
                    ),
                    author=author,
                    content=content,
                    url=url_value,
                    created_at=created_at,
                    search_query=feed_name,
                )

                if signal:

                    all_results[
                        str(story_id)
                    ] = signal

        except Exception as error:

            print(
                f"MCP: Lobsters parsing error "
                f"for {feed_name}: {error}"
            )

    results = list(
        all_results.values()
    )

    print(
        f"MCP: Lobsters collected "
        f"{len(results)} unique signals."
    )

    return results


# ============================================================
# MCP TOOL 1
# MULTI-SOURCE DEMAND COLLECTION
# ============================================================

@mcp.tool
def search_demand_signals() -> list[dict]:
    """
    Aggregate public demand signals from five sources:

    1. Hacker News
    2. Stack Overflow
    3. GitHub
    4. DEV Community
    5. Lobsters

    Each source is isolated so that a temporary failure
    does not stop the rest of the agent.
    """

    print(
        "\n"
        + "=" * 60
    )

    print(
        "MCP: MULTI-SOURCE DEMAND COLLECTION"
    )

    print(
        "=" * 60
    )

    all_signals = []

    # --------------------------------------------------------
    # Source 1
    # --------------------------------------------------------

    try:

        hn_results = search_hacker_news()

        all_signals.extend(
            hn_results
        )

    except Exception as error:

        print(
            f"MCP: Hacker News source "
            f"failed: {error}"
        )

    # --------------------------------------------------------
    # Source 2
    # --------------------------------------------------------

    try:

        stack_results = search_stack_exchange()

        all_signals.extend(
            stack_results
        )

    except Exception as error:

        print(
            f"MCP: Stack Overflow source "
            f"failed: {error}"
        )

    # --------------------------------------------------------
    # Source 3
    # --------------------------------------------------------

    try:

        github_results = search_github()

        all_signals.extend(
            github_results
        )

    except Exception as error:

        print(
            f"MCP: GitHub source "
            f"failed: {error}"
        )

    # --------------------------------------------------------
    # Source 4
    # --------------------------------------------------------

    try:

        dev_results = search_dev_community()

        all_signals.extend(
            dev_results
        )

    except Exception as error:

        print(
            f"MCP: DEV source "
            f"failed: {error}"
        )

    # --------------------------------------------------------
    # Source 5
    # --------------------------------------------------------

    try:

        lobsters_results = search_lobsters()

        all_signals.extend(
            lobsters_results
        )

    except Exception as error:

        print(
            f"MCP: Lobsters source "
            f"failed: {error}"
        )

    # ========================================================
    # FINAL DEDUPLICATION
    # ========================================================

    unique_signals = {}

    for signal in all_signals:

        source = signal.get(
            "source",
            "Unknown",
        )

        source_id = signal.get(
            "source_id",
            "",
        )

        if not source_id:

            continue

        unique_key = (
            f"{source}:{source_id}"
        )

        unique_signals[
            unique_key
        ] = signal

    results = list(
        unique_signals.values()
    )

    # ========================================================
    # SOURCE SUMMARY
    # ========================================================

    source_counts = {}

    for signal in results:

        source = signal.get(
            "source",
            "Unknown",
        )

        source_counts[
            source
        ] = (
            source_counts.get(
                source,
                0,
            )
            + 1
        )

    print(
        "\n"
        + "=" * 60
    )

    print(
        "MCP: COLLECTION SUMMARY"
    )

    print(
        "=" * 60
    )

    for source, count in sorted(
        source_counts.items()
    ):

        print(
            f"{source}: {count}"
        )

    print(
        f"TOTAL UNIQUE SIGNALS: "
        f"{len(results)}"
    )

    print(
        "=" * 60
    )

    return results


# ============================================================
# MCP TOOL 2
# SAVE QUALIFIED LEADS TO GOOGLE SHEETS
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
            "GCP_CREDENTIALS environment "
            "variable is missing."
        )

    creds_dict = json.loads(
        credentials
    )

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
                "SHEET_ID environment "
                "variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(
            sheet_id
        )

        # ----------------------------------------------------
        # Get or create worksheet
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

        existing_values = (
            worksheet.get_all_values()
        )

        # ----------------------------------------------------
        # Header
        # ----------------------------------------------------

        if not existing_values:

            worksheet.append_row(
                headers
            )

            existing_source_ids = set()

        else:

            existing_source_ids = set()

            for row in existing_values[1:]:

                if (
                    len(row) > 2
                    and row[2]
                ):

                    existing_source_ids.add(
                        str(
                            row[1]
                            + ":"
                            + row[2]
                        )
                    )

        rows_to_add = []

        duplicates = 0

        detected_at = datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        # ----------------------------------------------------
        # Deduplicate and prepare rows
        # ----------------------------------------------------

        for lead in leads:

            source = str(
                lead.get(
                    "source",
                    "Unknown",
                )
            ).strip()

            source_id = str(
                lead.get(
                    "source_id",
                    "",
                )
            ).strip()

            if not source_id:

                continue

            duplicate_key = (
                f"{source}:{source_id}"
            )

            if (
                duplicate_key
                in existing_source_ids
            ):

                duplicates += 1

                continue

            rows_to_add.append([
                detected_at,

                source,

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
                duplicate_key
            )

        # ----------------------------------------------------
        # Write
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
            "added": len(
                rows_to_add
            ),
            "duplicates": duplicates,
        }

    except Exception as error:

        print(
            f"MCP: Google Sheets error: "
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
    Log every autonomous agent execution into Run Log.
    """

    try:

        sheet_id = os.environ.get(
            "SHEET_ID"
        )

        if not sheet_id:

            raise RuntimeError(
                "SHEET_ID environment "
                "variable is missing."
            )

        gc = get_google_client()

        spreadsheet = gc.open_by_key(
            sheet_id
        )

        # ----------------------------------------------------
        # Get or create Run Log
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
        # Headers
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

            error[:500],
        ])

        print(
            "MCP: Run successfully logged."
        )

        return True

    except Exception as error:

        print(
            f"MCP: Could not log run: "
            f"{error}"
        )

        return False


# ============================================================
# START MCP SERVER
# ============================================================

if __name__ == "__main__":

    print(
        "Starting Ticmint Custom "
        "MCP Server..."
    )

    mcp.run()
