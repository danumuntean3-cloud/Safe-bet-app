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

st.set_page_config(page_title="Safe Accumulator AI", page_icon="⚽", layout="centered")

def get_cookie_manager():
    return stx.CookieManager(key="cookie_manager")

cookie_manager = get_cookie_manager()


# --- AUTHENTICATION MODULE ---
def check_auth():
    # Read saved session cookie
    saved_role = cookie_manager.get(cookie="auth_role")
    
    if "authenticated" not in st.session_state:
        if saved_role in ["admin", "user"]:
            st.session_state.authenticated = True
            st.session_state.role = saved_role
        else:
            st.session_state.authenticated = False
            st.session_state.role = None

    if not st.session_state.authenticated:
        st.title("🔒 Restricted Access")
        password = st.text_input("Enter Passcode:", type="password")
        if st.button("Login"):
            admin_pass = st.secrets.get("ADMIN_PASSWORD", "admin123")
            user_pass = st.secrets.get("USER_PASSWORD", "user123")
            
            if password == admin_pass:
                st.session_state.authenticated = True
                st.session_state.role = "admin"
                # Admin session (10 years)
                admin_expiry = datetime.datetime.now() + datetime.timedelta(days=3650)
                cookie_manager.set("auth_role", "admin", expires_at=admin_expiry, key="set_admin")
                st.rerun()
                
            elif password == user_pass:
                st.session_state.authenticated = True
                st.session_state.role = "user"
                # Guest session (Expires strictly after 10 minutes)
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
    match: str = Field(description="Match title, e.g., 'Brentford vs Chelsea'")
    league: str = Field(description="League name")
    selection: str = Field(description="Specific outcome, e.g., 'Double Chance 1X'")
    market: str = Field(description="Market type")
    odds: float = Field(description="Decimal odds (1.15 to 1.50)")
    rationale: str = Field(description="Floor rationale under 15 words")

class Ticket(BaseModel):
    ticket_name: str = Field(description="Safe Floor Slip or Double-Chance Buffer")
    total_odds: float = Field(description="Target combined odds 2.00 - 3.00")
    projected_return_10_stake: float = Field(description="Return on $10 stake")
    legs: List[BetLeg]

class SafeBetSlipResponse(BaseModel):
    safe_ticket_1: Ticket
    safe_ticket_2: Ticket

# --- HISTORY & ACTIVE FILE MANAGEMENT ---
HISTORY_FILE = "history.json"
ACTIVE_FILE = "active_slips.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_history(tickets):
    history = load_history()
    for t in tickets:
        history.append({
            "name": t["ticket_name"],
            "total_odds": t["total_odds"],
            "status": "PENDING",
            "legs": t["legs"]
        })
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

def load_active_slips():
    if os.path.exists(ACTIVE_FILE):
        try:
            with open(ACTIVE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_active_slips(slips_data: dict):
    try:
        with open(ACTIVE_FILE, "w") as f:
            json.dump(slips_data, f, indent=2)
    except Exception:
        pass

# --- FETCH ODDS & GENERATE SLIPS ---
def fetch_fixtures() -> List[dict]:
    odds_api_key = os.getenv("ODDS_API_KEY", "")
    if not odds_api_key:
        return [
            {"match": "Bayern Munich vs Union Berlin", "league": "Bundesliga", "h2h": [1.25, 6.0, 10.0]},
            {"match": "Brentford vs Chelsea", "league": "Premier League", "h2h": [3.4, 3.5, 2.1]}
        ]
    url = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
    params = {"apiKey": odds_api_key, "regions": "eu,uk", "markets": "h2h,totals", "oddsFormat": "decimal"}
    try:
        res = requests.get(url, params=params, timeout=8)
        return res.json()[:6]
    except Exception:
        return []

def generate_safe_slips(fixtures_data) -> SafeBetSlipResponse:
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        st.error("Missing GEMINI_API_KEY in Secrets!")
        st.stop()

    client = genai.Client(api_key=gemini_key)
    prompt = f"Analyze these fixtures: {json.dumps(fixtures_data)}. Generate EXACTLY TWO SAFE slips (Target total odds strictly between 2.00 and 3.00)."

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SafeBetSlipResponse,
            temperature=0.1,
        ),
    )
    return SafeBetSlipResponse.model_validate_json(response.text)

# --- TAB INTERFACE ---
tab1, tab2 = st.tabs(["🎯 Active Slips Generator", "📜 Bet History & Tracker"])

with tab1:
    # 1. Admin button always stays at the top of Active Slips tab
    if st.session_state.role == "admin":
        if st.button("🔄 Generate Today's Safe Slips", type="primary"):
            with st.spinner("Analyzing match metrics & floor consistency..."):
                fixtures = fetch_fixtures()
                slips = generate_safe_slips(fixtures)
                
                # Format to convert Pydantic validation into dictionaries for files
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
                # Save as current active slips + append to bet history file
                save_active_slips(slips_data)
                save_history([slips_data["safe_ticket_1"], slips_data["safe_ticket_2"]])
                st.success("Slips generated and logged to history!")
                st.rerun()

    # 2. Both Admin AND Guests see Today's Active Slips if they exist
    active_data = load_active_slips()
    
    if active_data:
        st.subheader("🎯 Today's Active Slips")
        
        # Display Slip 1
        st.markdown(f"### 🟢 {active_data['safe_ticket_1']['ticket_name']}")
        st.metric("Total Odds", f"{active_data['safe_ticket_1']['total_odds']:.2f}")
        for leg in active_data['safe_ticket_1']['legs']:
            st.write(f"• **{leg['match']}** ({leg['market']}): **{leg['selection']}** @ {leg['odds']}")
            st.caption(f"_{leg['rationale']}_")

        st.write("---")

        # Display Slip 2
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
    st.subheader("Historical Performance Tracker")
    history_data = load_history()
    if not history_data:
        st.write("No historical slips recorded yet.")
    else:
        for idx, ticket in enumerate(reversed(history_data)):
            status_color = "🔴" if ticket["status"] == "LOST" else ("🟢" if ticket["status"] == "WON" else "🟡")
            with st.expander(f"{status_color} {ticket['name']} — Target Odds: {ticket['total_odds']} [{ticket['status']}]"):
                for leg in ticket["legs"]:
                    st.write(f"- {leg['match']}: **{leg['selection']}** ({leg['odds']})")
