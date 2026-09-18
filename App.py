import os
import json
import requests
import datetime
import streamlit as st
import extra_streamlit_components as stx
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Page setup
st.set_page_config(page_title="Safe Accumulator AI", page_icon="⚽", layout="centered")

# --- COOKIE MANAGER & AUTHENTICATION ---
cookie_manager = stx.CookieManager(key="cookie_manager")

def check_auth():
    # 1. Check if session_state is already authenticated in active runtime memory
    if st.session_state.get("authenticated", False):
        return

    # 2. Fetch browser cookies
    cookies = cookie_manager.get_all()
    
    # 3. Hydration Guard: Wait for frontend cookie component to load on page refresh
    if cookies is None or not isinstance(cookies, dict):
        st.stop()

    saved_role = cookies.get("auth_role")

    # 4. Auto-login if a valid persistent cookie exists
    if saved_role in ["admin", "user"]:
        st.session_state.authenticated = True
        st.session_state.role = saved_role
        st.rerun()

    # 5. Fallback to Login UI if no cookie is present
    st.session_state.authenticated = False
    st.session_state.role = None

    st.title("🔒 Restricted Access")
    password = st.text_input("Enter Passcode:", type="password")
    if st.button("Login"):
        admin_pass = st.secrets.get("ADMIN_PASSWORD", "admin123")
        user_pass = st.secrets.get("USER_PASSWORD", "user123")
        
        if password == admin_pass:
            st.session_state.authenticated = True
            st.session_state.role = "admin"
            admin_expiry = datetime.datetime.now() + datetime.timedelta(days=3650)
            cookie_manager.set("auth_role", "admin", expires_at=admin_expiry, key="set_admin")
            st.rerun()
            
        elif password == user_pass:
            st.session_state.authenticated = True
            st.session_state.role = "user"
            user_expiry = datetime.datetime.now() + datetime.timedelta(minutes=10)
            cookie_manager.set("auth_role", "user", expires_at=user_expiry, key="set_user")
            st.rerun()
        else:
            st.error("Invalid passcode.")
    st.stop()

check_auth()

# --- HEADER & ROLE BADGE ---
st.title("⚽ Daily Safe Bet Slips")
st.caption(f"Logged in as: **{st.session_state.role.upper()}**")

if st.button("Logout"):
    cookie_manager.delete("auth_role", key="delete_cookie")
    st.session_state.authenticated = False
    st.session_state.role = None
    st.rerun()

# --- PYDANTIC SCHEMAS ---
class BetLeg(BaseModel):
    match: str = Field(description="Home Team vs Away Team")
    market: str = Field(description="e.g., Double Chance, Over 1.5 Goals")
    selection: str = Field(description="Specific outcome, e.g., 1X or Over 1.5")
    odds: float = Field(description="Decimal odds, e.g., 1.25")
    rationale: str = Field(description="Data-backed rationale citing stats, injuries, form, or xG")

class BetTicket(BaseModel):
    ticket_name: str = Field(description="Ticket title e.g. Conservative Floor")
    total_odds: float = Field(description="Combined ticket odds")
    legs: List[BetLeg]

class SafeBetSlipResponse(BaseModel):
    safe_ticket_1: BetTicket
    safe_ticket_2: BetTicket

# --- GEMINI & STORAGE HELPERS ---
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

SLIPS_FILE = "active_slips.json"
HISTORY_FILE = "history.json"

def load_active_slips():
    if os.path.exists(SLIPS_FILE):
        with open(SLIPS_FILE, "r") as f:
            return json.load(f)
    return None

def save_active_slips(data):
    with open(SLIPS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(new_slips):
    history = load_history()
    for slip in new_slips:
        history.append({
            "name": slip["ticket_name"],
            "total_odds": slip["total_odds"],
            "legs": slip["legs"],
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "status": "PENDING"
        })
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def fetch_fixtures():
    """Fetches all upcoming global football matches from The Odds API."""
    api_key = st.secrets.get("ODDS_API_KEY")
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={api_key}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Odds API Error: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Failed to fetch fixtures: {e}")
        return []

def generate_safe_slips(fixtures_data):
    """Deep AI engine executing an Institutional 16-Point Checklist with Google Search Grounding."""
    prompt = f"""
    You are an elite quantitative sports betting syndicate analyst.
    
    Live global football fixtures data:
    {json.dumps(fixtures_data)}

    --- INSTITUTIONAL 16-POINT MATCH EVALUATION ---
    Use Google Search Grounding to perform live web searches and evaluate candidate matches across all 16 variables:
    1. SQUAD AVAILABILITY: Key missing starters (injuries, suspensions, international duty).
    2. RECENT FORM: Last 5 matches, win/loss trends, clean sheet frequency.
    3. xG METRICS: Over/underperformance against Expected Goals (xG vs actual goals).
    4. VENUE & TURF: Home vs Away splits and artificial pitch surfaces.
    5. HEAD-TO-HEAD (H2H): Historical matchup trends over the last 3 seasons.
    6. REST DELTA: Days of rest since the last match for both teams.
    7. MOTIVATION: Title race, relegation battle, or dead-rubber game context.
    8. TACTICAL FIT: High-press vs low-block styles and defensive line depth.
    9. GOALKEEPER METRICS: Starting keeper form and PSxG efficiency.
    10. SET-PIECE MATCHUPS: Corner/free-kick threat vs opponent aerial defending.
    11. BENCH DEPTH: Squad quality for late-game 5-sub tactical adjustments.
    12. ENVIRONMENT: Severe weather (heavy rain, high winds, extreme cold/heat).
    13. TRAVEL & JETLAG: Long travel distances or international duty fatigue.
    14. REFEREE STRICTNESS: High yellow/red card or penalty trends.
    15. CLUB MORALE: New manager bounce, contract disputes, or financial turmoil.
    16. LINE MOVEMENTS: Sharp odds movements and market adjustments.

    --- MARKET RULES & CONSTRAINTS ---
    - Select strictly low-volatility, high-probability floor markets:
      • Double Chance (1X or X2)
      • Over 1.5 Total Goals
      • Under 3.5 / Under 4.5 Goals
      • Asian Handicap (+1.5 or +2.0)
      • Team Total Goals (Over 0.5)
    - Individual Leg Odds: Target strict floor odds between 1.15 and 1.45.
    - Safe Ticket 1 ("Conservative Floor"): Combined odds 1.60 – 2.20 (2-3 legs max).
    - Safe Ticket 2 ("Balanced Value"): Combined odds 2.20 – 3.50 (3-4 legs max).
    - Rationales: Explicitly state at least 2 verified statistical metrics or squad facts per selection.
    """

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            response_mime_type="application/json",
            response_schema=SafeBetSlipResponse,
            temperature=0.1,
        ),
    )

    return SafeBetSlipResponse.model_validate_json(response.text)

# --- TAB INTERFACE ---
tab1, tab2 = st.tabs(["🎯 Active Slips Generator", "📜 Bet History & Tracker"])

with tab1:
    if st.session_state.role == "admin":
        st.subheader("⚙️ Admin Controls")
        confirm_generate = st.checkbox("Confirm: Fetch live odds & run paid Gemini AI generation")
        
        if st.button("🔄 Generate Today's Safe Slips", type="primary", disabled=not confirm_generate):
            with st.spinner("Executing 16-Point Institutional Analysis & Google Grounding..."):
                fixtures = fetch_fixtures()
                slips = generate_safe_slips(fixtures)
                
                slips_data = {
                    "safe_ticket_1": {
                        "ticket_name": slips.safe_ticket_1.ticket_name,
                        "total_odds": slips.safe_ticket_1.total_odds,
                        "legs": [leg.dict() for leg in slips.safe_ticket_1.legs]
                    },
                    "safe_ticket_2": {
                        "ticket_name": slips.safe_ticket_2.ticket_name,
                        "total_odds": slips.safe_ticket_2.total_odds,
                        "legs": [leg.dict() for leg in slips.safe_ticket_2.legs]
                    }
                }
                
                save_active_slips(slips_data)
                save_history([slips_data["safe_ticket_1"], slips_data["safe_ticket_2"]])
                st.success("Slips generated and logged successfully!")
                st.rerun()

    active_data = load_active_slips()
    
    if active_data:
        st.subheader("🎯 Today's Active Slips")
        
        st.markdown(f"### 🟢 {active_data['safe_ticket_1']['ticket_name']}")
        st.metric("Total Odds", f"{active_data['safe_ticket_1']['total_odds']:.2f}")
        for leg in active_data['safe_ticket_1']['legs']:
            st.write(f"• **{leg['match']}** ({leg['market']}): **{leg['selection']}** @ {leg['odds']}")
            st.caption(f"_{leg['rationale']}_")

        st.write("---")

        st.markdown(f"### 🔵 {active_data['safe_ticket_2']['ticket_name']}")
        st.metric("Total Odds", f"{active_data['safe_ticket_2']['total_odds']:.2f}")
        for leg in active_data['safe_ticket_2']['legs']:
            st.write(f"• **{leg['match']}** ({leg['market']}): **{leg['selection']}** @ {leg['odds']}")
            st.caption(f"_{leg['rationale']}_")
    else:
        st.warning("⚠️ No slips have been generated for today yet.")
        if st.session_state.role != "admin":
            st.info("Please wait for the Admin to generate today's safe slips.")

with tab2:
    st.subheader("📜 Historical Performance Tracker")
    history_data = load_history()
    
    if not history_data:
        st.info("No historical slips recorded yet.")
    else:
        total_slips = len(history_data)
        won_slips = sum(1 for t in history_data if t.get("status") == "WON")
        lost_slips = sum(1 for t in history_data if t.get("status") == "LOST")
        pending_slips = sum(1 for t in history_data if t.get("status") == "PENDING")
        
        settled_slips = won_slips + lost_slips
        win_rate = (won_slips / settled_slips * 100) if settled_slips > 0 else 0.0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Slips", total_slips)
        col2.metric("Won 🟢", won_slips)
        col3.metric("Lost 🔴", lost_slips)
        col4.metric("Win Rate", f"{win_rate:.1f}%")

        if pending_slips > 0:
            st.caption(f"⏳ **{pending_slips}** slip(s) currently pending settlement.")

        st.write("---")

        for idx, ticket in enumerate(reversed(history_data)):
            real_index = len(history_data) - 1 - idx
            status = ticket.get("status", "PENDING")
            status_icon = "🟢" if status == "WON" else ("🔴" if status == "LOST" else "🟡")
            
            with st.expander(f"{status_icon} {ticket['name']} — Target Odds: {ticket['total_odds']:.2f} [{status}]"):
                if st.session_state.role == "admin":
                    c1, c2, c3 = st.columns(3)
                    if c1.button("Mark Won 🟢", key=f"won_{real_index}"):
                        history_data[real_index]["status"] = "WON"
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history_data, f, indent=4)
                        st.rerun()
                    if c2.button("Mark Lost 🔴", key=f"lost_{real_index}"):
                        history_data[real_index]["status"] = "LOST"
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history_data, f, indent=4)
                        st.rerun()
                    if c3.button("Reset Pending 🟡", key=f"pend_{real_index}"):
                        history_data[real_index]["status"] = "PENDING"
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history_data, f, indent=4)
                        st.rerun()

                st.write("**Legs:**")
                for leg in ticket["legs"]:
                    st.write(f"• {leg['match']}: **{leg['selection']}** ({leg['odds']})")

