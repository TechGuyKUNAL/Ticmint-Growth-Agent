# Ticmint Demand Capture Agent

An AI-powered demand capture agent built for Ticmint to identify potential event ticketing opportunities from public online conversations.

The basic idea is simple:

**Find people talking about events and ticketing problems, understand whether there is a real business opportunity, and put the useful ones into a Google Sheet for further action.**

I built this as a lightweight growth automation rather than a large data platform. The agent uses a custom MCP server to collect demand signals, Gemini to analyse and qualify them, and Google Sheets as the final working output.

---

# What the Agent Does

The agent looks for public conversations that could indicate a potential opportunity for Ticmint.

It is specifically looking for signals around:

* Event organisers
* Event operators
* Conferences
* Festivals
* Community events
* Ticketing platforms
* Event registration
* Eventbrite and similar platforms
* Ticketing fees
* Poor checkout experiences
* Branding limitations
* API or integration problems
* Customer support issues
* Payout problems
* Attendee management
* Data ownership
* People looking for alternatives to their current platform

The important part is that the agent is **not simply looking for negative comments**.

A complaint by itself isn't enough.

The person also needs to look like someone who is actually involved in organising or operating events, and there needs to be some evidence that the problem could have commercial relevance for Ticmint.

---

# Architecture

The current architecture is intentionally quite simple:

```text
                GitHub Actions
                      |
                      v
                  agent.py
                      |
                      v
              Custom MCP Server
                      |
                      v
        search_demand_signals()
                      |
                      v
             Public Web Signals
                      |
                      v
                Gemini LLM
                      |
                      v
          Qualification + Scoring
                      |
                      v
          save_qualified_leads()
                      |
                      v
                Google Sheets
                      |
                      v
             log_agent_run()
```

There are essentially four important pieces in the system.

### 1. Agent

`agent.py` controls the overall workflow.

It connects to the MCP server, requests the available demand signals, sends them to Gemini for analysis, saves qualified opportunities and logs the result of the run.

### 2. Custom MCP Server

The project includes a custom MCP server in:

```text
mcp_server.py
```

The MCP server is not just sitting there for the sake of satisfying the architecture requirement.

It is responsible for the actual tools used by the agent, including:

```text
search_demand_signals
save_qualified_leads
log_agent_run
```

This gives the agent a clean way to interact with the data collection and Google Sheets layer.

### 3. Gemini

Gemini is the reasoning layer.

The raw public signals are sent to the model along with the Ticmint qualification criteria.

The model then decides whether the signal is worth keeping and assigns an opportunity score.

### 4. Google Sheets

Google Sheets is the final output.

Qualified opportunities are written into the sheet through the MCP server.

The sheet therefore becomes the practical working list rather than the agent simply producing a terminal output.

---

# How Qualification Works

One of the decisions I made was to avoid treating every mention of Eventbrite or ticketing as a lead.

The agent checks for several things.

### Event organiser evidence

Is the person actually involved in an event or organisation?

### Current ticketing platform

Do we know what platform they are currently using?

If we don't know, the agent records:

```text
Unknown
```

rather than guessing.

### Specific pain

Is there an actual problem?

For example:

* Fees
* Branding
* Checkout
* API limitations
* Integration
* Support
* Payouts
* Attendee management
* Data ownership

### Switching intent

Are they actively considering an alternative?

This is much stronger than someone casually mentioning a ticketing platform.

### Urgency

Is there a current event, upcoming launch or active problem that makes the opportunity more timely?

### Ticmint fit

Does the situation appear relevant to what Ticmint actually provides?

---

# Opportunity Scoring

The agent uses a 100-point scoring model.

| Signal                                | Maximum Score |
| ------------------------------------- | ------------: |
| Event organiser evidence              |            20 |
| Current ticketing platform identified |            15 |
| Specific ticketing pain               |            20 |
| Switching / alternative intent        |            20 |
| Urgency / timing                      |            10 |
| Event scale / business relevance      |            10 |
| Ticmint fit                           |             5 |
| **Total**                             |       **100** |

Only opportunities scoring **60 or above** are passed into the qualified lead output.

I deliberately used a threshold rather than asking Gemini to return everything it finds.

Otherwise the output becomes noisy very quickly.

---

# What Gemini Produces

For every qualified opportunity, the agent tries to produce structured information including:

```text
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
```

The `why_this_lead` field is particularly important.

I don't just want:

> "This looks like a good prospect."

I want the model to explain **why** it thinks the conversation is commercially relevant.

The outreach draft also needs to reference the actual problem found in the conversation.

It should not turn into a generic:

> "Hi, Ticmint is a leading event ticketing platform..."

type of message.

---

# Google Sheets Output

The qualified opportunities are saved into Google Sheets.

The agent also checks for duplicates before adding new leads.

The output therefore becomes something that a growth or sales person can actually review.

The sheet can be used to look at:

* Who the person is
* Where the signal came from
* What they were talking about
* What platform they appear to use
* What problem they mentioned
* How urgent the problem appears
* Whether they are considering alternatives
* The opportunity score
* Why the agent considered it relevant
* A possible outreach starting point

---

# Scheduled Execution

The agent is designed to run through GitHub Actions rather than requiring a manual execution every time.

The workflow triggers:

```text
python agent.py
```

The workflow handles the environment variables and credentials required by the agent.

The basic flow is:

```text
Scheduled GitHub Action
        ↓
Run agent.py
        ↓
Connect to MCP
        ↓
Search demand signals
        ↓
Analyse with Gemini
        ↓
Save qualified leads
        ↓
Log the run
```

This means the output can continue updating without me manually exporting data after every run.

---

# Setup

Someone wanting to run the project should first clone the repository.

```bash
git clone https://github.com/TechGuyKUNAL/Ticmint-Growth-Agent.git
cd Ticmint-Growth-Agent
```

Install the required Python packages:

```bash
pip install -r requirements.txt
```

The project requires the following environment variables:

```text
GEMINI_API_KEY
GCP_CREDENTIALS
SHEET_ID
GEMINI_MODEL
```

### Gemini

`GEMINI_API_KEY` is used to access the Gemini API.

The model can be controlled through:

```text
GEMINI_MODEL
```

For example:

```text
gemini-3.6-flash
```

### Google Sheets

`GCP_CREDENTIALS` contains the Google Cloud credentials used by the MCP server to interact with Google Sheets.

`SHEET_ID` identifies the destination spreadsheet.

These credentials should be stored securely as GitHub Actions secrets and should never be committed into the repository.

### Local run

Once the environment variables are configured, the agent can be tested locally using:

```bash
python agent.py
```

The agent should then connect to the MCP server, retrieve the signals, analyse them and write qualified opportunities to the configured Google Sheet.

---

# Where It Breaks

This is the part I would be most honest about.

The current version works, but there are some obvious areas where it can break.

## 1. Gemini availability

The LLM is an external dependency.

During testing, a Gemini request returned:

```text
503 UNAVAILABLE
This model is currently experiencing high demand.
```

The important thing is that the collection part had already worked. The failure happened when the agent tried to call the model.

The current code allows that error to surface and the run fails.

If I were taking this into production, I'd add proper retry and exponential backoff around the Gemini request.

I would also consider a fallback model/provider so a temporary model outage doesn't stop the whole pipeline.

## 2. Source collection

The demand signal collection is another dependency.

If a source changes its structure, blocks requests, changes its response format or becomes unavailable, the number and quality of signals can drop.

This is one reason I wouldn't assume that a scraper is "set and forget".

I'd monitor the number of signals returned per source over time.

A sudden drop from normal volume would be a useful warning.

## 3. LLM qualification

The biggest quality risk is probably not technical.

It's the model misunderstanding intent.

Someone might mention Eventbrite without actually being an event organiser.

Someone might complain about ticketing but have no buying intent.

The model could also interpret a vague statement as stronger intent than it really is.

That's why I treat the output as **a sales signal, not a confirmed lead**.

A human should still review important opportunities before outreach.

## 4. Duplicate signals

The same conversation can potentially appear again on another run.

The current MCP workflow handles duplicate checking when saving leads, but a more advanced version would also use stronger content-level deduplication.

## 5. Cost

The biggest cost driver at scale would be the LLM.

Sending every piece of collected content to Gemini would be wasteful.

If the amount of data increases significantly, I'd first filter and normalise the raw signals and only send the more relevant ones to the LLM.

That would reduce both token consumption and processing time.

---

# What I Would Monitor

I wouldn't consider a GitHub Action being marked "successful" as proof that the agent is working well.

I'd monitor:

| Metric                              | What it tells me                                       |
| ----------------------------------- | ------------------------------------------------------ |
| Signals collected                   | Whether data collection is healthy                     |
| Qualified opportunities             | Whether the system is finding potential demand         |
| Qualification rate                  | Whether the system is becoming too broad or too strict |
| Duplicate rate                      | Whether repeated signals are becoming a problem        |
| Gemini success rate                 | Whether the reasoning layer is reliable                |
| Average opportunity score           | Whether signal quality is changing                     |
| Human accepted opportunities        | Whether the output is actually useful                  |
| Opportunities converted to pipeline | Whether the system is producing business value         |

The last two are the metrics I'd care about most.

A system that produces 500 leads but only one is worth contacting isn't really doing a good job.

---

# Human in the Loop

I intentionally don't let the AI make the final sales decision.

The agent can identify a potential opportunity and draft an outreach message.

It should not automatically decide:

> "Contact this person and send the email."

There is still a human decision between the AI output and actual outreach.

That's important because the cost of a bad sales message is higher than the cost of missing one weak lead.

I'd rather have a salesperson review 20 strong signals than have an autonomous system send 500 irrelevant messages.

---

# Current Limitations

The current version is a working MVP, not a finished production system.

The main limitations are:

* The LLM is currently a single point of failure.
* Source availability can change.
* Scraping can be fragile.
* Lead qualification still depends heavily on the model.
* Enrichment is limited.
* The system does not yet learn from which leads sales accepts or rejects.
* Outreach is drafted but still requires human review.
* The scoring model is rule-based and has not yet been trained against historical Ticmint outcomes.

I think these are acceptable limitations for the first version because the objective was to prove the workflow rather than build a full sales intelligence platform.

---

# What I'd Build Next With Another Week

If I had another week, I wouldn't immediately add ten more features.

I'd improve the quality of the signals first.

### 1. Source-level monitoring

I'd track each source separately and alert when one suddenly stops returning data.

### 2. Better deduplication

I'd use URL matching, source IDs and content similarity to reduce repeated opportunities.

### 3. Lead enrichment

For high-scoring opportunities, I'd try to enrich the company and event information where it can be verified.

The important word here is **verified**.

I don't want enrichment to become another place where the AI starts making things up.

### 4. Better lead scoring

After collecting enough historical data, I'd compare the AI's scores against human decisions.

For example:

```text
AI Score → Human Accepted → Sales Qualified → Opportunity → Closed
```

That would let me understand whether an 80-point lead is actually better than a 65-point lead.

### 5. Feedback loop

Eventually, I would want sales to mark a lead as:

```text
Useful
Not useful
Already known
Wrong person
No intent
Converted
```

That feedback could then be used to improve the qualification logic.

---

# What Success Looks Like

For me, success isn't:

> "The agent found 10,000 conversations."

That's just volume.

I'd rather have:

```text
1,000 raw signals
        ↓
200 relevant signals
        ↓
40 high-confidence opportunities
        ↓
20 human-approved leads
        ↓
5 real sales conversations
        ↓
Actual pipeline
```

The exact numbers will change, but the principle stays the same.

The agent should reduce the amount of manual research the growth team has to do while improving the quality of conversations that reach sales.

---

# Final Note

I built this as a practical growth automation rather than trying to make it look more complicated than it is.

The interesting part for me isn't the scraping or the LLM call by itself.

It's the decision layer in between:

**What is just internet noise, and what is actually a buying signal?**

That's where I think the real value of this type of agent sits.

The first version proves that workflow end to end:

**public demand signal → AI qualification → scored opportunity → Google Sheet → human review.**
