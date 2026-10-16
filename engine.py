import os
import json
import time
import urllib.parse
from datetime import datetime, timezone
import feedparser
from supabase import create_client, Client
from google import genai
from google.genai import types
import resend

# 1. Clean any invisible spaces (\xa0) or extra URL paths from GitHub Secrets
def clean_secret(val):
    if not val:
        return ""
    return val.replace("\xa0", "").strip()

SUPABASE_URL = clean_secret(os.environ.get("SUPABASE_URL")).split("/rest/v1")[0].rstrip("/")
SUPABASE_KEY = clean_secret(os.environ.get("SUPABASE_KEY"))
GEMINI_API_KEY = clean_secret(os.environ.get("GEMINI_API_KEY"))
RESEND_API_KEY = clean_secret(os.environ.get("RESEND_API_KEY"))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY

def fetch_targeted_news(sector, geography):
    """Fetches global macro news PLUS targeted sector & geography intelligence feeds."""
    query = urllib.parse.quote(f"{sector} {geography} geopolitics OR supply chain OR trade")
    feeds = [
        f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://feeds.bbci.co.uk/news/business/rss.xml"
    ]
    news_items = []
    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:8]:
            title = entry.get("title", "")
            desc = entry.get("description", "")
            news_items.append(f"- {title}: {desc}")
    return "\n".join(news_items)

def generate_strategic_brief(user_profile, raw_news):
    """Curates a concise, domain-specific briefing in the exact OSINTSUM editorial style."""
    sector = user_profile.get("sector") or "Global Markets"
    geography = user_profile.get("geography") or "Global"

    prompt = f"""
    You are the Chief Intelligence Editor at Avellon Intelligence.
    From the following recent global and sector news developments:
    {raw_news}

    Curate a highly focused, domain-specific daily intelligence briefing strictly for:
    - Target Sector: {sector}
    - Target Geography: {geography}

    Follow this exact editorial style:
    - Filter out noise. Select ONLY the 4 most critical developments impacting {sector} and {geography}.
    - Write with crisp, British/international intelligence-briefing precision (no fluff, no clichés).
    - Return STRICT JSON matching this exact structure:
    {{
      "lead_headline": "A single punchy sentence linking the top 3 developments in this briefing.",
      "items": [
        {{
          "category": "Sectoral Impact" or "{geography}",
          "topic": "Short bold prefix (e.g., 'Maritime trade', 'Oil shipping', 'India', 'Red Sea', 'Semiconductors')",
          "fact": "Sentence 1 (Regular font): A crisp, factual 1-sentence summary of what happened.",
          "implication": "Sentence 2 (Italic font): A sharp 1-to-2 sentence strategic assessment explaining the second-order operational, commercial, regulatory, or supply-chain consequence.",
          "deep_dive": "A detailed 2-paragraph strategic analysis and actionable risk mitigation recommendation for the full website version."
        }}
      ]
    }}
    """

    # Auto-retry up to 4 times if Google's server has a temporary 503 spike
    for attempt in range(1, 5):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"Attempt {attempt} encountered server busy/error: {e}")
            if attempt < 4:
                print("Waiting 15 seconds before retrying...")
                time.sleep(15)
            else:
                raise e

def build_full_web_content(date_str, sector, geography, data):
    """Formats the comprehensive deep-dive report stored in Supabase for the website."""
    blocks = [
        f"AVELLON'S DAILY BRIEF — {date_str}",
        f"Domain: {sector} | Region: {geography}",
        f"Executive Lead: {data.get('lead_headline', '')}\n"
    ]
    for idx, item in enumerate(data.get("items", []), 1):
        blocks.append(
            f"{idx}. {item.get('topic')}: {item.get('fact')}\n"
            f"Strategic Implication: {item.get('implication')}\n\n"
            f"Deep-Dive Analysis:\n{item.get('deep_dive')}\n"
            f"{'-'*60}"
        )
    return "\n\n".join(blocks)

def build_email_html(date_str, sector, geography, data, read_url):
    """Builds the clean OSINTSUM-style email with Bold Topic + Fact + Italic Implication + Read more link."""
    items_html = ""
    current_category = None

    for item in data.get("items", []):
        category = item.get("category", sector)
        if category != current_category:
            current_category = category
            items_html += f"""
            <h3 style="color: #b8860b; font-size: 16px; font-weight: bold; margin: 24px 0 12px 0; border-bottom: 1px solid #eee; padding-bottom: 4px;">
                {category}
            </h3>
            """

        items_html += f"""
        <div style="margin-bottom: 18px; font-size: 14.5px; line-height: 1.55; color: #111111;">
            <strong>{item.get('topic')}:</strong> {item.get('fact')}
            <em>{item.get('implication')}</em><br>
            <a href="{read_url}" style="color: #1a56db; text-decoration: none; font-size: 13.5px;">Read more</a>
        </div>
        """

    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 620px; margin: 0 auto; color: #111111; padding: 16px;">
        <h1 style="font-size: 24px; font-weight: bold; margin-bottom: 12px; color: #0b2545;">
            Avellon's Daily Brief: {date_str}
        </h1>
        <p style="font-size: 16px; font-weight: bold; color: #333333; line-height: 1.45; margin-bottom: 12px;">
            {data.get('lead_headline', '')}
        </p>
        <p style="margin-top: 0; margin-bottom: 24px;">
            <a href="{read_url}" style="color: #111111; text-decoration: underline; font-size: 13px;">Read online</a>
        </p>

        <div style="text-align: center; padding: 20px 0; border-top: 2px solid #0b2545; border-bottom: 1px solid #e5e7eb; margin-bottom: 20px;">
            <div style="font-size: 26px; font-weight: 800; letter-spacing: 1.5px; color: #0b2545;">AVELLON</div>
            <div style="font-size: 16px; font-weight: bold; color: #b8860b; margin-top: 4px;">Daily Strategic Briefing</div>
            <div style="font-size: 13px; color: #555555; margin-top: 4px;">
                Focus: <strong>{sector}</strong> &bull; <strong>{geography}</strong>
            </div>
        </div>

        {items_html}

        <div style="margin-top: 30px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center;">
            <a href="{read_url}" style="background-color: #0b2545; color: #ffffff; padding: 11px 22px; text-decoration: none; border-radius: 4px; font-size: 14px; font-weight: bold; display: inline-block;">
                Read Full Deep-Dive Analysis on Avellon Intelligence &rarr;
            </a>
            <p style="font-size: 11.5px; color: #777777; margin-top: 18px;">
                &copy; {datetime.now(timezone.utc).year} Avellon Intelligence. All rights reserved.
            </p>
        </div>
    </div>
    """

def run_daily_pipeline():
    print("Starting Avellon Intelligence Pipeline...")
    today_str = datetime.now(timezone.utc).strftime("%d %B %Y")

    # Fetch active subscribers from Supabase
    users_response = supabase.table("subscribers").select("*").eq("is_active", True).execute()
    subscribers = users_response.data

    if not subscribers:
        print("No active subscribers found in database yet.")
        return

    for user in subscribers:
        sector = user.get("sector") or "Global Markets"
        geography = user.get("geography") or "Global"
        print(f"Curating brief for {user['email']} ({sector} - {geography})...")

        try:
            # 1. Fetch domain & geography specific news
            raw_news = fetch_targeted_news(sector, geography)

            # 2. Generate OSINTSUM-style curated brief
            generated_data = generate_strategic_brief(user, raw_news)

            teaser_text = generated_data.get("lead_headline", "")
            full_web_text = build_full_web_content(today_str, sector, geography, generated_data)

            # 3. Save Full Deep-Dive Brief into Supabase daily_briefs table
            db_insert = supabase.table("daily_briefs").insert({
                "user_id": user["id"],
                "teaser": teaser_text,
                "full_content": full_web_text
            }).execute()

            brief_id = db_insert.data[0]["id"]
            read_url = f"https://www.avellonintelligence.com/brief?id={brief_id}"

            # 4. Build and send the concise curated email
            html_email = build_email_html(today_str, sector, geography, generated_data, read_url)

            resend.Emails.send({
                "from": "Avellon Intelligence <onboarding@resend.dev>",
                "to": [user["email"]],
                "subject": f"Avellon's Daily Brief: {today_str} ({sector})",
                "html": html_email
            })
            print(f"Successfully sent curated brief to {user['email']}!")

        except Exception as e:
            print(f"Error processing {user['email']}: {e}")
            raise e

if __name__ == "__main__":
    run_daily_pipeline()
