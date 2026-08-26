import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from fastmcp import FastMCP

# Define Custom MCP Server
mcp = FastMCP("TicmintAgent")

@mcp.tool
def fetch_data() -> list[dict]:
    """Fetches real recent event organizer posts from Reddit."""
    print("Scraping live Reddit data...")
    url = "https://www.reddit.com/r/EventProduction/new.json?limit=10"
    headers = {"User-Agent": "TicmintGrowthAgent/1.0"}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            posts = []
            for item in res.json().get("data", {}).get("children", []):
                p = item["data"]
                if p.get("selftext"):
                    posts.append({
                        "author": p.get("author", "user"),
                        "content": p.get("selftext", "")[:300],
                        "url": f"https://reddit.com{p.get('permalink')}"
                    })
            return posts
        else:
            print(f"Reddit blocked the IP with status code {res.status_code}.")
            return []
    except Exception as e:
        print(f"Reddit Scraping Error: {e}")
        return []

@mcp.tool
def save_to_sheet(rows: list[list[str]]) -> bool:
    """Saves leads to Google Sheets."""
    try:
        creds_dict = json.loads(os.environ.get("GCP_CREDENTIALS"))
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(os.environ.get("SHEET_ID"))
        sh.sheet1.append_rows(rows)
        return True
    except Exception as e:
        print(f"SHEET ERROR: {e}")
        return False

def main():
    print("Starting Live Agent...")
    posts = fetch_data()
    
    if not posts:
        print("No data fetched from Reddit (likely blocked). Exiting pipeline.")
        return
        
    print(f"Evaluating {len(posts)} posts with AI...")
    
    prompt = f"""
    You are a Growth Lead. Read these Reddit posts.
    Identify ONLY posts where the user is frustrated with their current ticketing platform.
    If no one is complaining, return an empty JSON array: []
    Otherwise, return a valid JSON array of objects with keys: author, url, pain_point, outreach_draft.
    Posts: {json.dumps(posts)}
    """
    
    api_key = os.environ.get("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        })
        
        data = res.json()
        
        if 'error' in data:
            print(f"Gemini API Error: {data['error'].get('message', 'Unknown API Error')}")
            return
            
        raw_text = data['candidates'][0]['content']['parts'][0]['text']
        
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3]
            
        leads = json.loads(raw_text)
        
        if not leads:
            print("AI determined no users are complaining today. Exiting smoothly.")
            return
            
        rows = [[L.get("author",""), L.get("url",""), L.get("pain_point",""), L.get("outreach_draft","")] for L in leads]
        print(f"Found {len(rows)} qualified leads! Saving to sheet...")
        
        success = save_to_sheet(rows)
        if success:
            print("SUCCESS: Data saved to Google Sheet!")
        
    except Exception as e:
        print(f"Pipeline failed during AI evaluation: {e}")

if __name__ == "__main__":
    main()
