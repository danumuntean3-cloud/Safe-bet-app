import os
import json
import requests
import streamlit as st
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# STREAMLIT UI CONFIGURATION (OPTIMIZED FOR ANDROID PHONE SCREENS)
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Safe Accumulator AI", page_icon="⚽", layout="centered")
st.title("⚽ Daily Safe Bet Slips (Low Odds)")
st.caption("AI-Powered Floor & Buffer Accumulators (Target Odds: 2.00 – 2.80)")

# ---------------------------------------------------------------------------
# PYDANTIC SCHEMAS FOR STRICT JSON OUTPUT (2 SAFE SLIPS)
# ---------------------------------------------------------------------------
class BetLeg(BaseModel):
    match: str = Field(description="Match title, e.g., 'Brentford vs Chelsea'")
    league: str = Field(description="League name, e.g., 'Premier League'")
    selection: str = Field(description="Specific low-risk outcome picked")
    market: str = Field(description="Market type, e.g., 'Double Chance (1X)', 'Over 1.5'")
    odds: float = Field(description="Decimal odds for this leg (1.15 to 1.45)")
    rationale: str = Field(description="Tactical/floor reason under 15 words")

class Ticket(BaseModel):
    ticket_name: str = Field(description="e.g. 'Safe Floor Slip' or 'Double-Chance Buffer Slip'")
    total_odds: float = Field(description="Product of individual leg odds (Target 2.00 - 3.00)")
    projected_return_10_stake: float = Field(description="Return on a $10 / £10 stake")
    legs: List[BetLeg]


class SafeBetSlipResponse(BaseModel):
    safe_ticket_1: Ticket  # Floor-Verified Slip (Target 2.00 - 2.40)
    safe_ticket_2: Ticket  # Double-Chance Buffer Slip (Target 2.30 - 2.80)

# ---------------------------------------------------------------------------
# FETCH LIVE ODDS
# ---------------------------------------------------------------------------
def fetch_fixtures() -> List[dict]:
    odds_api_key = os.getenv("ODDS_API_KEY", "")
    if not odds_api_key:
        # Fallback fixtures for Sep 18, 2026 if API key is not set
        return [
            {"match": "Bayern Munich vs Union Berlin", "league": "Bundesliga", "h2h": [1.20, 6.50, 12.00]},
            {"match": "Brentford vs Chelsea", "league": "Premier League", "h2h": [3.40, 3.50, 2.10]},
            {"match": "Bristol City vs Watford", "league": "Championship", "h2h": [2.40, 3.20, 2.90]},
            {"match": "Espanyol vs Elche", "league": "La Liga", "h2h": [2.10, 3.25, 3.60]}
        ]
    
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
    params = {"apiKey": odds_api_key, "regions": "eu,uk", "markets": "h2h,totals", "oddsFormat": "decimal"}
    try:
        res = requests.get(url, params=params, timeout=8)
        return res.json()[:6]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# GEMINI AI SLIP GENERATION
# ---------------------------------------------------------------------------
def generate_safe_slips(fixtures_data: List[dict]) -> SafeBetSlipResponse:
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        st.error("Missing GEMINI_API_KEY in Secrets!")
        st.stop()
        
    client = genai.Client(api_key=gemini_key)

    prompt = f"""
    Act as a strict quantitative sports handicapper focused ONLY on capital preservation and safe steady bankroll growth.
    Analyze these fixtures: {json.dumps(fixtures_data)}

    RULES:
    1. Generate EXACTLY TWO SAFE tickets using the live bookie odds provided in fixtures_data.
    2. Ticket 1 ('safe_ticket_1'): Safe Floor Slip (Target total odds: 2.00 - 2.50).
    3. Ticket 2 ('safe_ticket_2'): Double-Chance Buffer Slip (Target total odds: 2.45 - 3.00).
    4. Capping: Maximum 2 to 3 legs per ticket.
    5. Math Accuracy: Combined total_odds MUST equal the exact mathematical product of individual leg odds.

    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SafeBetSlipResponse,
            temperature=0.1,
        ),
    )
    return SafeBetSlipResponse.model_validate_json(response.text)

# ---------------------------------------------------------------------------
# UI BUTTON & DISPLAY
# ---------------------------------------------------------------------------
stake = st.slider("Select Stake (£/$):", min_value=5, max_value=100, value=10, step=5)

if st.button("🔄 Generate Today's Safe Slips", type="primary"):
    with st.spinner("Analyzing match metrics & floor consistency..."):
        fixtures = fetch_fixtures()
        slips = generate_safe_slips(fixtures)
        
        # DISPLAY TICKET 1
        t1 = slips.safe_ticket_1
        st.subheader(f"🟢 Ticket 1: {t1.ticket_name}")
        st.metric(label="Total Odds", value=f"{t1.total_odds:.2f}", delta=f"Est. Return: £{t1.total_odds * stake:.2f}")
        for leg in t1.legs:
            st.write(f"• **{leg.match}** ({leg.league}) — **{leg.market}: {leg.selection}** @ `{leg.odds:.2f}`")
            st.caption(f"  *Floor Rationale:* {leg.rationale}")
        
        st.divider()

        # DISPLAY TICKET 2
        t2 = slips.safe_ticket_2
        st.subheader(f"🛡️ Ticket 2: {t2.ticket_name}")
        st.metric(label="Total Odds", value=f"{t2.total_odds:.2f}", delta=f"Est. Return: £{t2.total_odds * stake:.2f}")
        for leg in t2.legs:
            st.write(f"• **{leg.match}** ({leg.league}) — **{leg.market}: {leg.selection}** @ `{leg.odds:.2f}`")
            st.caption(f"  *Floor Rationale:* {leg.rationale}")
