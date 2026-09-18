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
    # 1. Admin controls with safety checkbox safeguard
    if st.session_state.role == "admin":
        st.subheader("⚙️ Admin Controls")
        
        # Checkbox safeguard to prevent accidental paid API triggers
        confirm_generate = st.checkbox("Confirm: Fetch live odds & run paid Gemini AI generation")
        
        if st.button("🔄 Generate Today's Safe Slips", type="primary", disabled=not confirm_generate):
            with st.spinner("Analyzing match metrics & floor consistency..."):
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
                st.success("Slips updated successfully!")
                st.rerun()

    # 2. Display active slips from saved JSON file for both Admin and Guests
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
        # --- PERFORMANCE STATISTICS COUNTER ---
        total_slips = len(history_data)
        won_slips = sum(1 for t in history_data if t.get("status") == "WON")
        lost_slips = sum(1 for t in history_data if t.get("status") == "LOST")
        pending_slips = sum(1 for t in history_data if t.get("status") == "PENDING")
        
        # Win Rate calculation (excluding pending)
        settled_slips = won_slips + lost_slips
        win_rate = (won_slips / settled_slips * 100) if settled_slips > 0 else 0.0

        # Display Summary Dashboard Metrics in columns
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Slips", total_slips)
        col2.metric("Won 🟢", won_slips)
        col3.metric("Lost 🔴", lost_slips)
        col4.metric("Win Rate", f"{win_rate:.1f}%")

        if pending_slips > 0:
            st.caption(f"⏳ **{pending_slips}** slip(s) currently pending settlement.")

        st.write("---")

        # --- SLIP LIST DISPLAY ---
        for idx, ticket in enumerate(reversed(history_data)):
            status = ticket.get("status", "PENDING")
            status_icon = "🟢" if status == "WON" else ("🔴" if status == "LOST" else "🟡")
            
            with st.expander(f"{status_icon} {ticket['name']} — Target Odds: {ticket['total_odds']:.2f} [{status}]"):
                # Admin controls to mark status directly in history
                if st.session_state.role == "admin":
                    c1, c2, c3 = st.columns(3)
                    if c1.button("Mark Won 🟢", key=f"won_{idx}"):
                        history_data[len(history_data) - 1 - idx]["status"] = "WON"
                        save_history(history_data) # persists update
                        st.rerun()
                    if c2.button("Mark Lost 🔴", key=f"lost_{idx}"):
                        history_data[len(history_data) - 1 - idx]["status"] = "LOST"
                        save_history(history_data)
                        st.rerun()
                    if c3.button("Reset Pending 🟡", key=f"pend_{idx}"):
                        history_data[len(history_data) - 1 - idx]["status"] = "PENDING"
                        save_history(history_data)
                        st.rerun()

                st.write("**Legs:**")
                for leg in ticket["legs"]:
                    st.write(f"• {leg['match']}: **{leg['selection']}** ({leg['odds']})")


