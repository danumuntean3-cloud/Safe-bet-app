import os
import json
import math
import requests
import datetime
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import extra_streamlit_components as stx
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Page setup
st.set_page_config(page_title="Football Odds AI", page_icon="⚽", layout="centered")

# --- COOKIE MANAGER & AUTHENTICATION ---
cookie_manager = stx.CookieManager(key="cookie_manager")

def check_auth():
    if st.session_state.get("authenticated", False):
        return

    cookies = cookie_manager.get_all()
    if cookies is None:
        st.stop()

    saved_role = cookies.get("auth_role")

    if saved_role in ["admin", "user"]:
        st.session_state.authenticated = True
        st.session_state.role = saved_role
        st.rerun()

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

# --- HEADER & LOGOUT ---
st.title("⚽ Daily Safe Bet Slips")
st.caption(f"Role: **{st.session_state.role.upper()}**")

if st.button("Logout"):
    cookie_manager.delete("auth_role", key="delete_cookie")
    st.session_state.authenticated = False
    st.session_state.role = None
    st.rerun()

# --- SCHEMAS ---
class BetLeg(BaseModel):
    match: str = Field(description="Home Team vs Away Team")
    selection: str = Field(description="Selected Market Outcome (e.g. 1X, Over 1.5)")
    bookmaker_odds: float = Field(description="Decimal odds")
    model_probability: float = Field(description="Model probability between 0.0 and 1.0")

class BetTicket(BaseModel):
    ticket_name: str = Field(description="Ticket Title e.g., Safe Slip 1")
    legs: List[BetLeg]

class SafeBetSlipResponse(BaseModel):
    safe_ticket_1: BetTicket
    safe_ticket_2: BetTicket

# --- GEMINI & STORAGE ---
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
    api_key = st.secrets.get("ODDS_API_KEY")
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={api_key}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
    try:
        response = requests.get(url, timeout=10)
        return response.json() if response.status_code == 200 else []
    except Exception:
        return []

def generate_safe_slips(fixtures_data):
    prompt = f"""
    Analyze global football fixtures: {json.dumps(fixtures_data)}
    Using Poisson distribution models, pick high-probability floor selections (Double Chance 1X/X2, Over 1.5 Goals).
    Ensure odds are between 1.15 and 1.45.
    Output 2 slips:
    - Safe Ticket 1: 2-3 legs
    - Safe Ticket 2: 3-4 legs
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

def copy_to_clipboard_button(text_to_copy: str, button_id: str):
    """Renders a custom HTML/JS button to copy text directly to clipboard."""
    escaped_text = json.dumps(text_to_copy)
    html_code = f"""
    <button id="btn_{button_id}" onclick="copySlip_{button_id}()" style="
        background-color: #0E1117;
        color: #FAFAFA;
        border: 1px solid #4A4A4A;
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 14px;
        cursor: pointer;
        width: 100%;
        margin-top: 8px;
        transition: all 0.2s ease-in-out;
    ">📋 Copy Slip to Clipboard</button>

    <script>
    function copySlip_{button_id}() {{
        const text = {escaped_text};
        navigator.clipboard.writeText(text).then(function() {{
            const btn = document.getElementById("btn_{button_id}");
            btn.innerText = "✅ Copied!";
            btn.style.backgroundColor = "#28a745";
            btn.style.color = "#ffffff";
            setTimeout(function() {{
                btn.innerText = "📋 Copy Slip to Clipboard";
                btn.style.backgroundColor = "#0E1117";
                btn.style.color = "#FAFAFA";
            }}, 2000);
        }}).catch(function(err) {{
            alert("Failed to copy slip");
        }});
    }}
    </script>
    """
    components.html(html_code, height=50)

# --- UI TABS ---
tab1, tab2 = st.tabs(["🎯 Today's Slips", "📜 Performance History"])

with tab1:
    if st.session_state.role == "admin":
        if st.button("🔄 Generate Today's Slips", type="primary"):
            with st.spinner("Calculating probabilities..."):
                fixtures = fetch_fixtures()
                slips = generate_safe_slips(fixtures)

                odds1 = math.prod([leg.bookmaker_odds for leg in slips.safe_ticket_1.legs])
                odds2 = math.prod([leg.bookmaker_odds for leg in slips.safe_ticket_2.legs])

                slips_data = {
                    "safe_ticket_1": {
                        "ticket_name": slips.safe_ticket_1.ticket_name,
                        "total_odds": round(odds1, 2),
                        "legs": [leg.dict() for leg in slips.safe_ticket_1.legs]
                    },
                    "safe_ticket_2": {
                        "ticket_name": slips.safe_ticket_2.ticket_name,
                        "total_odds": round(odds2, 2),
                        "legs": [leg.dict() for leg in slips.safe_ticket_2.legs]
                    }
                }

                save_active_slips(slips_data)
                save_history([slips_data["safe_ticket_1"], slips_data["safe_ticket_2"]])
                st.success("Slips Updated!")
                st.rerun()

    active_data = load_active_slips()

    if active_data:
        for idx, ticket_key in enumerate(["safe_ticket_1", "safe_ticket_2"]):
            ticket = active_data[ticket_key]
            
            # Header
            st.subheader(f"{ticket['ticket_name']}")
            st.write(f"**Total Odds:** `{ticket['total_odds']:.2f}`")

            # Formatted text string for copying
            shareable_lines = [f"⚽ {ticket['ticket_name']} (Total Odds: {ticket['total_odds']:.2f})", ""]

            # Minimalist Clean Leg Cards
            for leg in ticket['legs']:
                prob_pct = leg.get('model_probability', 0) * 100
                shareable_lines.append(f"• {leg['match']} -> Pick: {leg['selection']} @ {leg['bookmaker_odds']:.2f} ({prob_pct:.0f}% win prob)")
                
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1.5, 1.5])
                    with c1:
                        st.markdown(f"**{leg['match']}**")
                        st.caption(f"Pick: **{leg['selection']}**")
                    with c2:
                        st.markdown("**Odds**")
                        st.write(f"`{leg['bookmaker_odds']:.2f}`")
                    with c3:
                        st.markdown("**Win Prob.**")
                        st.write(f"**{prob_pct:.0f}%**")

            # Render Copy Button for each ticket
            formatted_slip_text = "\n".join(shareable_lines)
            copy_to_clipboard_button(formatted_slip_text, button_id=f"slip_{idx}")

            st.divider()
    else:
        st.info("No slips generated for today yet.")

with tab2:
    st.subheader("📜 History")
    history_data = load_history()

    if not history_data:
        st.info("No history recorded yet.")
    else:
        won = sum(1 for t in history_data if t.get("status") == "WON")
        settled = sum(1 for t in history_data if t.get("status") in ["WON", "LOST"])
        win_rate = (won / settled * 100) if settled > 0 else 0.0

        st.metric("Win Rate", f"{win_rate:.1f}%")
        st.divider()

        for idx, ticket in enumerate(reversed(history_data)):
            real_index = len(history_data) - 1 - idx
            status = ticket.get("status", "PENDING")
            badge = "🟢" if status == "WON" else ("🔴" if status == "LOST" else "🟡")

            with st.expander(f"{badge} {ticket['name']} — Odds: {ticket['total_odds']:.2f}"):
                for leg in ticket["legs"]:
                    prob = leg.get('model_probability', 0) * 100
                    st.write(f"• **{leg['match']}**: {leg['selection']} @ **{leg['bookmaker_odds']:.2f}** ({prob:.0f}% prob)")
                
                if st.session_state.role == "admin" and status == "PENDING":
                    st.write("---")
                    col_w, col_l = st.columns(2)
                    if col_w.button("Mark Won 🟢", key=f"w_{real_index}"):
                        history_data[real_index]["status"] = "WON"
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history_data, f, indent=4)
                        st.rerun()
                    if col_l.button("Mark Lost 🔴", key=f"l_{real_index}"):
                        history_data[real_index]["status"] = "LOST"
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history_data, f, indent=4)
                        st.rerun()

