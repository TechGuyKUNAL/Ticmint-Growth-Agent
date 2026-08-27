import os
import json
import asyncio

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


# ============================================================
# GEMINI CLIENT
# ============================================================

def get_gemini_client():

    api_key = os.environ.get(
        "GEMINI_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "GEMINI_API_KEY environment variable is missing."
        )

    return genai.Client(
        api_key=api_key
    )


# ============================================================
# AI QUALIFICATION
# ============================================================

def analyse_signals(
    signals: list[dict],
) -> list[dict]:

    if not signals:
        return []

    client = get_gemini_client()

    prompt = f"""
You are a B2B Growth Lead working for Ticmint.

TICMINT CONTEXT

Ticmint is a white-label event ticketing and event management
platform.

It helps event organisers operate ticketing using their own
brand, domain and checkout while retaining control over
attendee data.

Your job is to identify genuine potential sales opportunities
from public online conversations.

Do NOT simply find negative comments.

A qualified opportunity should have evidence of:

1. The person is likely to be an event organiser, event
   operator, conference organiser, community organiser, festival
   organiser, business running events, or someone directly
   involved in organising events.

AND

2. They are discussing ticketing, event registration,
   Eventbrite, ticketing software, or a similar platform.

AND

3. There is a meaningful business pain or buying signal.

Examples:

- High ticketing fees
- Poor branding
- Lack of white-label experience
- Poor checkout experience
- API limitations
- Integration problems
- Poor customer support
- Data ownership concerns
- Payout problems
- Attendee management limitations
- Looking for an Eventbrite alternative
- Considering switching platforms
- Building a large event and evaluating platforms

DO NOT QUALIFY:

- People buying tickets.
- Casual Eventbrite mentions.
- News about Eventbrite.
- Investors discussing Eventbrite.
- Developers discussing ticketing APIs without an event use case.
- Generic technology discussions.
- Complaints without evidence of an organiser/business context.
- Conversations where there is clearly no commercial opportunity.

IMPORTANT:

Never invent facts.

If something is unknown, write "Unknown".

Do not assume event size, event type, company name, platform
or urgency unless there is evidence.

OPPORTUNITY SCORING

Score each potential opportunity from 0 to 100.

Event organiser evidence: 0-20

Current ticketing platform identified: 0-15

Specific ticketing pain: 0-20

Switching or alternative intent: 0-20

Urgency or timing: 0-10

Event scale or business relevance: 0-10

Ticmint fit: 0-5

Only return opportunities with a score of 60 or higher.

OUTPUT FIELDS

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

OUTREACH

Write a short personalised outreach message.

The message must refer to the specific problem identified
in the conversation.

Do NOT use generic statements such as:

"Hi, Ticmint is a leading event ticketing platform."

Do NOT pretend you know information that is not present
in the source.

The outreach should sound like a human B2B sales message.

Return ONLY valid JSON.

EXPECTED JSON FORMAT:

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
    "pain_point": "Specific observed problem",
    "urgency": "High",
    "switching_intent": "High",
    "ticmint_fit": "High",
    "opportunity_score": 85,
    "why_this_lead": "Evidence-based explanation",
    "outreach_draft": "Short personalised outreach"
  }}
]

PUBLIC CONVERSATIONS:

{json.dumps(
    signals,
    ensure_ascii=False
)}
"""

    # ========================================================
    # GEMINI REQUEST
    # ========================================================

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    # ========================================================
    # READ GEMINI RESPONSE
    # ========================================================

    if not response.text:

        print(
            "Gemini returned an empty response."
        )

        return []

    text = response.text.strip()

    # ========================================================
    # PARSE JSON
    # ========================================================

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

    # ========================================================
    # VERIFY JSON STRUCTURE
    # ========================================================

    if not isinstance(result, list):

        print(
            "Gemini response was not a JSON array."
        )

        return []

    # ========================================================
    # FINAL SAFETY FILTER
    # ========================================================

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

        except (TypeError, ValueError):

            score = 0

        if score >= 60:

            lead["opportunity_score"] = score

            qualified.append(
                lead
            )

    return qualified


# ============================================================
# MAIN AGENT
# ============================================================

async def main():

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
            # FETCH SIGNALS
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

                print(
                    f"Leads added: {leads_added}"
                )

                print(
                    f"Duplicates skipped: {duplicates}"
                )

            else:

                leads_added = 0

                duplicates = 0

                print(
                    "No high-intent opportunities "
                    "were identified."
                )

            # =================================================
            # LOG RUN
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

        # ====================================================
        # TRY TO LOG FAILURE
        # ====================================================

        try:

            async with Client(mcp) as client:

                await client.call_tool(
                    "log_agent_run",
                    {
                        "signals_found": len(
                            signals
                        ),
                        "qualified_leads": 0,
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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
