import os
import json
import asyncio

from google import genai
from google.genai import types
from fastmcp import Client

from mcp_server import mcp


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash",
)


# ---------------------------------------------------------
# Gemini
# ---------------------------------------------------------

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is missing."
        )

    return genai.Client(api_key=api_key)


def analyse_signals(signals: list[dict]) -> list[dict]:
    """
    Uses Gemini to identify genuine event-organiser
    opportunities from public conversations.
    """

    if not signals:
        return []

    client = get_gemini_client()

    prompt = f"""
You are a B2B Growth Lead working for Ticmint.

Ticmint is a white-label event ticketing and management
platform. It helps event organisers operate ticketing under
their own brand, domain and checkout while retaining control
over attendee data.

Your job is NOT to identify every negative comment.

Your job is to identify public conversations that represent
a potentially valuable sales opportunity for Ticmint.

QUALIFY A SIGNAL ONLY IF THERE IS REASONABLE EVIDENCE THAT:

1. The person is an event organiser, event operator, business,
   community organiser, conference organiser, festival organiser,
   or someone directly involved in running events.

AND

2. They are discussing a ticketing platform or ticketing
   workflow.

AND

3. There is a meaningful pain point, dissatisfaction,
   limitation, cost issue, support problem, branding issue,
   API issue, checkout issue, data ownership issue, payout
   issue, or evidence they are considering alternatives.

Do NOT qualify:

- Casual mentions of Eventbrite.
- News about ticketing companies.
- Developers merely discussing APIs without an event use case.
- Consumers complaining about buying a ticket.
- Generic discussions with no commercial opportunity.
- Comments where the event-organiser connection is extremely weak.

IMPORTANT:

Do not invent facts.

If event size, event type, company or platform is unknown,
write "Unknown".

SCORING:

Opportunity score is 0-100.

Event organiser evidence: 0-20
Current platform identified: 0-15
Specific ticketing pain: 0-20
Switching/alternative intent: 0-20
Urgency/timing: 0-10
Event scale/business relevance: 0-10
Ticmint product fit: 0-5

Only return leads with an opportunity_score >= 60.

For each qualified lead return:

- qualified
- source
- source_id
- author
- url
- current_platform
- event_type
- event_scale
- pain_category
- pain_point
- urgency
- switching_intent
- ticmint_fit
- opportunity_score
- why_this_lead
- outreach_draft

OUTREACH RULES:

The outreach must reference the person's actual problem.

Do NOT write generic messages such as:
"Hi, Ticmint is a leading event ticketing platform..."

Instead, connect the message directly to the observed problem.

Do not claim that Ticmint definitely solves something unless
the relationship is reasonably supported by the information
provided.

Keep each outreach draft concise and human.

Return ONLY valid JSON.

Expected format:

[
  {{
    "qualified": true,
    "source": "Hacker News",
    "source_id": "123",
    "author": "username",
    "url": "https://...",
    "current_platform": "Eventbrite",
    "event_type": "Conference",
    "event_scale": "Unknown",
    "pain_category": "Branding",
    "pain_point": "Specific problem",
    "urgency": "High",
    "switching_intent": "High",
    "ticmint_fit": "High",
    "opportunity_score": 85,
    "why_this_lead": "Reason",
    "outreach_draft": "Personalized message"
  }}
]

PUBLIC SIGNALS:

{json.dumps(signals, ensure_ascii=False)}
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    text = response.text.strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        print("Gemini returned invalid JSON.")
        print(text[:2000])
        return []


# ---------------------------------------------------------
# Main agent
# ---------------------------------------------------------

async def main():
    print("=" * 60)
    print("TICMINT AUTONOMOUS DEMAND CAPTURE AGENT")
    print("=" * 60)

    signals = []
    qualified_leads = []
    save_result = {}
    run_status = "SUCCESS"
    run_error = ""

    try:

        # -------------------------------------------------
        # Connect to custom MCP server
        # -------------------------------------------------

        print("\n[1/4] Connecting to custom MCP server...")

        async with Client(mcp) as client:

            print("MCP connection established.")

            # -------------------------------------------------
            # Fetch public signals
            # -------------------------------------------------

            print("\n[2/4] Fetching public demand signals...")

            result = await client.call_tool(
                "search_demand_signals"
            )

            signals = result.data or []

            print(
                f"MCP returned {len(signals)} signals."
            )

            if not signals:
                print(
                    "No signals found. Ending run safely."
                )

                await client.call_tool(
                    "log_agent_run",
                    {
                        "signals_found": 0,
                        "new_signals": 0,
                        "qualified_leads": 0,
                        "duplicates": 0,
                        "status": "NO_DATA",
                        "error": "",
                    },
                )

                return

            # -------------------------------------------------
            # AI qualification
            # -------------------------------------------------

            print("\n[3/4] Evaluating signals with Gemini...")

            qualified_leads = analyse_signals(signals)

            print(
                f"Gemini identified "
                f"{len(qualified_leads)} qualified opportunities."
            )

            # -------------------------------------------------
            # Save results
            # -------------------------------------------------

            print("\n[4/4] Saving qualified leads via MCP...")

            if qualified_leads:

                save_result = await client.call_tool(
                    "save_qualified_leads",
                    {
                        "leads": qualified_leads
                    },
                )

                save_data = save_result.data or {}

                print(
                    f"Added: {save_data.get('added', 0)}"
                )

                print(
                    f"Duplicates: "
                    f"{save_data.get('duplicates', 0)}"
                )

            else:

                save_result = {
                    "added": 0,
                    "duplicates": 0,
                }

                print(
                    "No high-intent opportunities found."
                )

            # -------------------------------------------------
            # Run logging
            # -------------------------------------------------

            save_data = (
                save_result.data
                if hasattr(save_result, "data")
                else save_result
            ) or {}

            await client.call_tool(
                "log_agent_run",
                {
                    "signals_found": len(signals),
                    "new_signals": len(qualified_leads),
                    "qualified_leads": len(qualified_leads),
                    "duplicates": save_data.get(
                        "duplicates", 0
                    ),
                    "status": "SUCCESS",
                    "error": "",
                },
            )

    except Exception as exc:

        run_status = "ERROR"
        run_error = str(exc)

        print("\nAGENT ERROR:")
        print(exc)

        # Attempt to log failure through MCP
        try:

            async with Client(mcp) as client:

                await client.call_tool(
                    "log_agent_run",
                    {
                        "signals_found": len(signals),
                        "new_signals": 0,
                        "qualified_leads": 0,
                        "duplicates": 0,
                        "status": run_status,
                        "error": run_error,
                    },
                )

        except Exception as log_error:

            print(
                f"Could not log failure: {log_error}"
            )

        raise


if __name__ == "__main__":
    asyncio.run(main())
