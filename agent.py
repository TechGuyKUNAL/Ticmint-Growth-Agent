import os
import json
import asyncio
import time

from google import genai
from google.genai import types
from fastmcp import Client

from mcp_server import mcp

# ============================================================

# CONFIGURATION

# ============================================================

GEMINI_MODEL = os.environ.get(
"GEMINI_MODEL",
"gemini-3.6-flash",
)

MAX_GEMINI_RETRIES = 4
INITIAL_RETRY_DELAY = 10

# ============================================================

# GEMINI CLIENT

# ============================================================

def get_gemini_client():
"""
Create and return the Gemini client using the
GEMINI_API_KEY GitHub secret.
"""

```
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is missing."
    )

return genai.Client(
    api_key=api_key
)
```

# ============================================================

# GEMINI ANALYSIS

# ============================================================

def analyse_signals(
signals: list[dict],
) -> list[dict]:
"""
Analyse collected public internet conversations and
identify genuine Ticmint sales opportunities.

```
Gemini 503 errors are retried automatically.
"""

if not signals:
    return []

client = get_gemini_client()

prompt = f"""
```

You are a B2B Growth Lead working for Ticmint.

Your job is to identify genuine potential sales opportunities
from public online conversations collected from multiple
internet sources.

============================================================
TICMINT CONTEXT
===============

Ticmint is a white-label event ticketing and event management
platform.

It helps event organisers operate ticketing using their own
brand, domain and checkout while retaining control over
attendee data.

Ticmint serves event organisers, businesses, communities,
conference organisers, festivals and other event operators.

The goal of this agent is NOT to find every mention of
ticketing.

The goal is to find conversations where there is a credible
commercial opportunity for Ticmint.

============================================================
QUALIFICATION LOGIC
===================

A conversation should generally qualify only when there is
evidence for BOTH:

1. ORGANISER / BUSINESS CONTEXT

The person appears to be:

* An event organiser
* Event operator
* Conference organiser
* Festival organiser
* Community organiser
* Business running events
* Event technology decision maker
* Someone directly involved in organising or operating events

AND

2. TICKETING / EVENT PLATFORM CONTEXT

They are discussing:

* Eventbrite
* Ticketmaster
* Tito
* Eventzilla
* Universe
* Humanitix
* Event ticketing
* Event registration
* Ticketing software
* Event management software
* Event platforms
* Checkout
* Attendee management
* Event registration systems

AND preferably there is a meaningful business signal.

============================================================
BUYING SIGNALS
==============

Strong buying signals include:

* High ticketing fees
* Transaction fees
* Poor branding
* Lack of white-label experience
* Poor checkout experience
* Poor user experience
* Platform limitations
* API limitations
* Integration problems
* Poor customer support
* Data ownership concerns
* Attendee data limitations
* Payout problems
* Reporting limitations
* Event management limitations
* Looking for an alternative
* Considering switching platforms
* Evaluating multiple platforms
* Building a large event
* Planning an upcoming event
* Frustration with an existing provider
* Need for branded ticketing
* Need for own domain
* Need for control over attendee data

============================================================
DO NOT QUALIFY
==============

Do NOT qualify:

* People simply buying tickets
* Casual mentions of Eventbrite
* News articles or news discussions
* Investors discussing Eventbrite
* Generic software discussions
* Developers discussing APIs without an event use case
* People asking how to attend an event
* Generic complaints without organiser/business context
* Academic discussions
* Historical discussions with no commercial intent
* Conversations where there is clearly no sales opportunity

============================================================
IMPORTANT EVIDENCE RULE
=======================

Never invent facts.

Only use information contained in the supplied conversation.

If something is unknown, write:

"Unknown"

Do NOT assume:

* Event size
* Event type
* Company name
* Budget
* Location
* Platform
* Urgency
* Job title
* Buying authority
* Switching timeline

unless there is evidence.

============================================================
OPPORTUNITY SCORING
===================

Score every potential opportunity from 0 to 100.

Use the following framework:

Event organiser evidence: 0-20

Current ticketing platform identified: 0-15

Specific ticketing pain: 0-20

Switching or alternative intent: 0-20

Urgency or timing: 0-10

Event scale or business relevance: 0-10

Ticmint fit: 0-5

Only return opportunities with a score of 60 or higher.

============================================================
OUTPUT FIELDS
=============

For every qualified opportunity return:

qualified
source
source_id
author
url
current_platform
event_type
event_scale
pain_category
pain_point
urgency
switching_intent
ticmint_fit
opportunity_score
why_this_lead
outreach_draft

============================================================
OUTREACH RULES
==============

Write a short personalised B2B outreach message.

The message must reference the specific problem identified
in the conversation.

Do NOT write generic messages such as:

"Hi, Ticmint is a leading event ticketing platform."

Do not pretend to know information that is not present.

Do not invent:

* Event size
* Revenue
* Company information
* Job title
* Budget
* Timeline

The outreach should sound like a human sales message.

Keep it concise.

============================================================
OUTPUT FORMAT
=============

Return ONLY valid JSON.

Return a JSON array.

Example:

[
{{
"qualified": true,
"source": "Hacker News",
"source_id": "12345",
"author": "username",
"url": "https://...",
"current_platform": "Eventbrite",
"event_type": "Conference",
"event_scale": "Unknown",
"pain_category": "Fees",
"pain_point": "The organiser is concerned about high ticketing fees.",
"urgency": "Medium",
"switching_intent": "High",
"ticmint_fit": "High",
"opportunity_score": 85,
"why_this_lead": "The conversation shows event organiser context and explicit dissatisfaction with the current ticketing platform.",
"outreach_draft": "Hi, noticed your point about the ticketing fees..."
}}
]

============================================================
PUBLIC INTERNET CONVERSATIONS
=============================

{json.dumps(
signals,
ensure_ascii=False
)}
"""

```
for attempt in range(1, MAX_GEMINI_RETRIES + 1):

    try:

        print(
            f"Gemini analysis attempt "
            f"{attempt}/{MAX_GEMINI_RETRIES}..."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        text = (response.text or "").strip()

        if not text:

            print(
                "Gemini returned an empty response."
            )

            return []

        try:

            result = json.loads(text)

        except json.JSONDecodeError:

            print(
                "Gemini returned invalid JSON."
            )

            print(
                text[:3000]
            )

            return []

        if not isinstance(result, list):

            print(
                "Gemini response was not a JSON array."
            )

            return []

        qualified = []

        for lead in result:

            if not isinstance(lead, dict):
                continue

            score = lead.get(
                "opportunity_score",
                0,
            )

            try:

                score = int(score)

            except (
                TypeError,
                ValueError,
            ):

                score = 0

            if score >= 60:

                lead["opportunity_score"] = score

                qualified.append(lead)

        return qualified

    except Exception as error:

        error_text = str(error)

        print(
            f"Gemini error on attempt "
            f"{attempt}: {error_text}"
        )

        # ------------------------------------------------
        # Retry temporary Gemini server errors
        # ------------------------------------------------

        if (
            "503" in error_text
            or "UNAVAILABLE" in error_text
            or "high demand" in error_text.lower()
            or "temporarily unavailable" in error_text.lower()
        ):

            if attempt < MAX_GEMINI_RETRIES:

                delay = (
                    INITIAL_RETRY_DELAY
                    * (2 ** (attempt - 1))
                )

                print(
                    f"Gemini appears temporarily "
                    f"unavailable."
                )

                print(
                    f"Waiting {delay} seconds "
                    f"before retry..."
                )

                time.sleep(delay)

                continue

        # ------------------------------------------------
        # Non-retryable error
        # ------------------------------------------------

        raise

return []
```

# ============================================================

# MAIN AGENT

# ============================================================

async def main():

```
print("=" * 60)
print(
    "TICMINT AUTONOMOUS DEMAND CAPTURE AGENT"
)
print("=" * 60)

signals = []
qualified_leads = []

try:

    # ====================================================
    # CONNECT TO MCP
    # ====================================================

    print(
        "\n[1/4] Connecting to custom MCP server..."
    )

    async with Client(mcp) as client:

        print(
            "MCP connection established."
        )

        # =================================================
        # FETCH INTERNET SIGNALS
        # =================================================

        print(
            "\n[2/4] Fetching public demand signals..."
        )

        search_result = await client.call_tool(
            "search_demand_signals"
        )

        signals = search_result.data or []

        print(
            f"MCP returned "
            f"{len(signals)} signals."
        )

        # ------------------------------------------------
        # Display a small sample for debugging
        # ------------------------------------------------

        if signals:

            print(
                "\n========== SAMPLE SIGNALS =========="
            )

            for signal in signals[:2]:

                print(
                    json.dumps(
                        signal,
                        ensure_ascii=False,
                        indent=2,
                    )[:3000]
                )

                print(
                    "\n***\n"
                )

        # =================================================
        # NO DATA
        # =================================================

        if not signals:

            print(
                "No signals found."
            )

            await client.call_tool(
                "log_agent_run",
                {
                    "signals_found": 0,
                    "qualified_leads": 0,
                    "leads_added": 0,
                    "duplicates": 0,
                    "status": "NO_DATA",
                    "error": "",
                },
            )

            return

        # =================================================
        # GEMINI ANALYSIS
        # =================================================

        print(
            "\n[3/4] Evaluating signals with Gemini..."
        )

        qualified_leads = analyse_signals(
            signals
        )

        print(
            f"Gemini identified "
            f"{len(qualified_leads)} "
            f"qualified opportunities."
        )

        # =================================================
        # SAVE TO GOOGLE SHEETS
        # =================================================

        print(
            "\n[4/4] Saving results via MCP..."
        )

        if qualified_leads:

            save_result = await client.call_tool(
                "save_qualified_leads",
                {
                    "leads": qualified_leads
                },
            )

            save_data = (
                save_result.data or {}
            )

            leads_added = save_data.get(
                "added",
                0,
            )

            duplicates = save_data.get(
                "duplicates",
                0,
            )

            save_success = save_data.get(
                "success",
                True,
            )

            print(
                f"Leads added: {leads_added}"
            )

            print(
                f"Duplicates skipped: {duplicates}"
            )

            if not save_success:

                raise RuntimeError(
                    save_data.get(
                        "error",
                        "Unknown Google Sheets error",
                    )
                )

        else:

            leads_added = 0
            duplicates = 0

            print(
                "No high-intent opportunities "
                "were identified."
            )

        # =================================================
        # LOG SUCCESSFUL RUN
        # =================================================

        await client.call_tool(
            "log_agent_run",
            {
                "signals_found": len(signals),
                "qualified_leads": len(
                    qualified_leads
                ),
                "leads_added": leads_added,
                "duplicates": duplicates,
                "status": "SUCCESS",
                "error": "",
            },
        )

        print(
            "\nAgent run completed successfully."
        )

except Exception as error:

    print(
        "\nAGENT ERROR:"
    )

    print(
        str(error)
    )

    # ----------------------------------------------------
    # Try to log failure
    # ----------------------------------------------------

    try:

        async with Client(mcp) as client:

            await client.call_tool(
                "log_agent_run",
                {
                    "signals_found": len(
                        signals
                    ),
                    "qualified_leads": len(
                        qualified_leads
                    ),
                    "leads_added": 0,
                    "duplicates": 0,
                    "status": "ERROR",
                    "error": str(error),
                },
            )

    except Exception as log_error:

        print(
            f"Could not log failure: "
            f"{log_error}"
        )

    raise
```

# ============================================================

# START

# ============================================================

if **name** == "**main**":

```
asyncio.run(main())
```
