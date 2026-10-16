import os
import json
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

def fetch_global_news():
    """Fetches top global news developments from open RSS feeds."""
    feeds = [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://feeds.bbci.co.uk/news/business/rss.xml"
    ]
    news_items = []
    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:8]:
            news_items.append(f"- {entry.title}: {entry.get('description', '')}")
    return "\n".join(news_items)

def generate_strategic_brief(user_profile, raw_news):
    """Generates a custom JSON teaser and full strategic brief via Gemini."""
    sector = user_profile.get("sector") or "Global Markets"
    geography = user_profile.get("geography") or "Global"

    prompt = f"""
    You are an elite geopolitical and strategic risk analyst at Avellon Intelligence.
    Analyze the following global developments from the last 24 hours:
    {raw_news}

    Target Client Profile:
    - Sector: {sector}
    - Geography Focus: {geography}

    Provide your strategic intelligence in strict JSON format with exactly two keys:
    1. "teaser": A high-impact, 2-to-3 sentence executive summary highlighting the #1 risk or strategic takeaway for their sector and region today (plain text string).
    2. "full_content": A comprehensive, structured 4-paragraph strategic intelligence briefing as a single plain text string (use \\n\\n between paragraphs) covering Geopolitical Risk, Supply Chain Impact, Economic Outlook, and Strategic Actionable Takeaway.
    """

    response = gemini_client.models.generate_content(
       model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )
    return json.loads(response.text)

def run_daily_pipeline():
    print("Starting Avellon Intelligence Pipeline...")
    raw_news = fetch_global_news()

    # Fetch active subscribers from Supabase
    users_response = supabase.table("subscribers").select("*").eq("is_active", True).execute()
    subscribers = users_response.data

    if not subscribers:
        print("No active subscribers found in database yet.")
        return

    for user in subscribers:
        print(f"Generating brief for {user['email']} ({user.get('sector')} - {user.get('geography')})...")
        try:
            # 1. Generate AI Brief
            generated_data = generate_strategic_brief(user, raw_news)

            teaser_text = str(generated_data.get("teaser", ""))
            full_content = generated_data.get("full_content", "")
            if isinstance(full_content, dict):
                full_content = "\n\n".join([f"{k}:\n{v}" for k, v in full_content.items()])
            elif isinstance(full_content, list):
                full_content = "\n\n".join([str(item) for item in full_content])
            else:
                full_content = str(full_content)

            # 2. Save Full Brief into Supabase daily_briefs table
            db_insert = supabase.table("daily_briefs").insert({
                "user_id": user["id"],
                "teaser": teaser_text,
                "full_content": full_content
            }).execute()

            brief_id = db_insert.data[0]["id"]

            # 3. Create link back to Avellon Intelligence website
            read_url = f"https://www.avellonintelligence.com/brief?id={brief_id}"

            # 4. Send Teaser Email via Resend
            html_email = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a; line-height: 1.6;">
                <h2 style="color: #0b2545; margin-bottom: 4px;">Avellon's Daily Brief</h2>
                <p style="color: #666; font-size: 13px; margin-top: 0;">
                    Sector: <strong>{user.get('sector')}</strong> | Region: <strong>{user.get('geography')}</strong>
                </p>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 16px 0;">
                <p style="font-size: 16px;"><strong>Executive Summary:</strong></p>
                <p style="font-size: 15px; background-color: #f8f9fa; padding: 15px; border-left: 4px solid #0b2545;">
                    {teaser_text}
                </p>
                <div style="margin: 28px 0;">
                    <a href="{read_url}" style="background-color: #0b2545; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">
                        Read Full Strategic Analysis &rarr;
                    </a>
                </div>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 24px 0;">
                <p style="font-size: 12px; color: #888;">&copy; Avellon Intelligence. All rights reserved.</p>
            </div>
            """

            resend.Emails.send({
                "from": "Avellon Intelligence <onboarding@resend.dev>",
                "to": [user["email"]],
                "subject": f"Avellon Daily Brief: {user.get('sector')} Strategic Update",
                "html": html_email
            })
            print(f"Successfully sent brief to {user['email']}!")

        except Exception as e:
            print(f"Error processing {user['email']}: {e}")
            raise e

if __name__ == "__main__":
    run_daily_pipeline()
