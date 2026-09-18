import os
import re
import json
import math
import requests
import datetime
import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Page setup
st.set_page_config(page_title="Quantitative Poisson +EV Engine", page_icon="⚽", layout="wide")

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

# --- HEADER & ROLE BADGE ---
st.title("⚽ Quantitative Poisson +EV Betting Engine")
st.caption(f"Logged in as: **{st.session_state.role.upper()}**")

if st.button("Logout"):
    cookie_manager.delete("auth_role", key="delete_cookie")
    st.session_state.authenticated = False
    st.session_state.role = None
    st.rerun()

# --- QUANTITATIVE POISSON MATH ENGINE ---

def poisson_pmf(k: int, mu: float) -> float:
    """Calculates Poisson probability for k goals given expected goals mu."""
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.pow(mu, k) * math.exp(-mu)) / math.factorial(k)

def calculate_scoreline_matrix(home_xg: float, away_xg: float, max_goals: int = 7):
    """Generates a scoreline probability matrix using bivariate Poisson distributions."""
    matrix = []
    for h in range(max_goals + 1):
        row = []
        p_home = poisson_pmf(h, home_xg)
        for a in range(max_goals + 1):
            p_away = poisson_pmf(a, away_xg)
            row.append(p_home * p_away)
        matrix.append(row)
    return matrix

def derive_market_probabilities(home_xg: float, away_xg: float):
    """Derives exact probability metrics across low-volatility markets."""
    matrix = calculate_scoreline_matrix(home_xg, away_xg)
    
    p_home_win, p_draw, p_away_win = 0.0, 0.0, 0.0
    p_over_1_5, p_under_3_5 = 0.0, 0.0
    
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            p = matrix[h][a]
            if h > a:
                p_home_win += p
            elif h == a:
                p_draw += p
            else:
                p_away_win += p
                
            if (h + a) > 1.5:
                p_over_1_5 += p
            if (h + a) < 3.5:
                p_under_3_5 += p

    return {
        "1X": p_home_win + p_draw,
        "X2": p_away_win + p_draw,
        "Over 1.5": p_over_1_5,
        "Under 3.5": p_under_3_5,
        "Home Win": p_home_win,
        "Away Win": p_away_win
    }

def calculate_ev(model_prob: float, bookmaker_odds: float) -> float:
    """Calculates Expected Value percentage: EV = (Prob * Odds) - 1"""
    return (model_prob * bookmaker_odds) - 1.0

# --- PYDANTIC SCHEMAS ---
class BetLeg(BaseModel):
    match: str = Field(description="Home Team vs Away Team")
    market: str = Field(description="Double Chance or Total Goals")
    selection: str = Field(description="1X, X2, Over 1.5, or Under 3.5")
    bookmaker_odds: float = Field(description="Best live decimal odds")
    estimated_home_xg: float = Field(description="Model projected Home Expected Goals")
    estimated_away_xg: float = Field(description="Model projected Away Expected Goals")
    model_probability: float = Field(description="Calculated Poisson probability between 0.0 and 1.0")
    expected_value_pct: float = Field(description="Calculated Expected Value percentage (e.g. 0.045 for +4.5% EV)")
    rationale: str = Field(description="Mathematical justification with team xG metrics, injuries, and form")

class BetTicket(BaseModel):
    ticket_name: str = Field(description="Ticket Title e.g., Quantitative Floor Ticket")
    legs: List[BetLeg]

class SafeBetSlipResponse(BaseModel):
    safe_ticket_1: BetTicket
    safe_ticket_2: BetTicket

# --- GEMINI & STORAGE HELPERS ---
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

SLIPS_FILE = "active_slips.json"
HISTORY_FILE = "history.json"

def _atomic_write(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)

def load_active_slips():
    if os.path.exists(SLIPS_FILE):
        with open(SLIPS_FILE, "r") as f:
            return json.load(f)
    return None

def save_active_slips(data):
    _atomic_write(SLIPS_FILE, data)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def recompute_ticket_status(legs):
    results = [l.get("result", "PENDING") for l in legs]
    if any(r == "LOST" for r in results):
        return "LOST"
    if results and all(r == "WON" for r in results):
        return "WON"
    return "PENDING"

def save_history(new_slips):
    history = load_history()
    for slip in new_slips:
        history.append({
            "name": slip["ticket_name"],
            "total_odds": slip["total_odds"],
            "legs": slip["legs"],
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "status": recompute_ticket_status(slip["legs"]),
        })
    _atomic_write(HISTORY_FILE, history)

def fetch_fixtures():
    """Fetches upcoming football matches and live odds from The Odds API."""
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
    """Uses Gemini as a stats researcher to build input parameters for Poisson +EV modeling."""
    prompt = f"""
    You are an elite quantitative football analyst specializing in Poisson goal distribution models and +EV detection.

    Live global football fixtures & market data:
    {json.dumps(fixtures_data)}

    --- QUANTITATIVE TASK INSTRUCTIONS ---
    1. Perform live Google searches for candidates to gather home/away Expected Goals (xG), goal trends, clean sheet percentages, and squad injury news.
    2. Estimate the baseline Home xG and Away xG for each candidate match based on recent statistics and lineup availability.
    3. Run Poisson distribution equations on your calculated xG parameters to get exact outcome probabilities for:
       - Double Chance (1X, X2)
       - Total Goals (Over 1.5, Under 3.5)
    4. Calculate Expected Value: EV = (Poisson Probability * Bookmaker Decimal Odds) - 1.0
    5. STRICT REQUIREMENT: Only select legs that demonstrate positive Expected Value (EV > +2.0%) and carry bookmaker floor odds between 1.15 and 1.45.
    6. Formulate 2 Tickets:
       - Safe Ticket 1 ("Quantitative EV Floor"): 2-3 legs, targeting target odds around 1.60 – 2.20.
       - Safe Ticket 2 ("Balanced Quantitative Value"): 3-4 legs, targeting target odds around 2.20 – 3.20.
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
tab1, tab2, tab3 = st.tabs(["🎯 Active Slips Generator", "📜 Bet History & Settlement", "📊 Poisson Calibration Audit"])

with tab1:
    if st.session_state.role == "admin":
        st.subheader("⚙️ Admin Controls")
        confirm_generate = st.checkbox("Confirm: Fetch live odds & run Quantitative Poisson Pipeline")

        if st.button("🔄 Generate Today's Poisson +EV Slips", type="primary", disabled=not confirm_generate):
            with st.spinner("Processing Poisson Goal Distributions & Grounded xG Data..."):
                fixtures = fetch_fixtures()
                slips = generate_safe_slips(fixtures)

                # Python explicitly calculates mathematically accurate combined odds
                odds1 = math.prod([leg.bookmaker_odds for leg in slips.safe_ticket_1.legs])
                odds2 = math.prod([leg.bookmaker_odds for leg in slips.safe_ticket_2.legs])

                slips_data = {
                    "safe_ticket_1": {
                        "ticket_name": slips.safe_ticket_1.ticket_name,
                        "total_odds": round(odds1, 2),
                        "legs": [leg.dict() for leg in slips.safe_ticket_1.legs],
                    },
                    "safe_ticket_2": {
                        "ticket_name": slips.safe_ticket_2.ticket_name,
                        "total_odds": round(odds2, 2),
                        "legs": [leg.dict() for leg in slips.safe_ticket_2.legs],
                    },
                }

                save_active_slips(slips_data)
                save_history([slips_data["safe_ticket_1"], slips_data["safe_ticket_2"]])
                st.success("Poisson +EV slips generated and logged successfully!")
                st.rerun()

    active_data = load_active_slips()

    if active_data:
        st.subheader("🎯 Today's Active Value Slips (+EV)")

        for ticket_key in ["safe_ticket_1", "safe_ticket_2"]:
            ticket = active_data[ticket_key]
            color_badge = "🟢" if ticket_key == "safe_ticket_1" else "🔵"

            st.markdown(f"### {color_badge} {ticket['ticket_name']}")
            st.metric("Combined Ticket Odds", f"{ticket['total_odds']:.2f}")

            for leg in ticket["legs"]:
                ev_pct = leg.get("expected_value_pct", 0) * 100
                prob_pct = leg.get("model_probability", 0) * 100

                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"• **{leg['match']}** ({leg['market']}): **{leg['selection']}** @ **{leg['bookmaker_odds']:.2f}**")
                    st.caption(f"_{leg['rationale']}_")
                with col2:
                    st.metric("Projected xG", f"{leg['estimated_home_xg']:.2f} - {leg['estimated_away_xg']:.2f}")
                with col3:
                    st.metric("Poisson Prob", f"{prob_pct:.1f}%")
                    st.caption(f"Calculated Edge: **+{ev_pct:.1f}% EV**")
            st.write("---")
    else:
        st.warning("⚠️ No slips generated for today yet.")

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
        col1.metric("Total Tickets", total_slips)
        col2.metric("Won 🟢", won_slips)
        col3.metric("Lost 🔴", lost_slips)
        col4.metric("Win Rate", f"{win_rate:.1f}%")

        st.write("---")

        for idx, ticket in enumerate(reversed(history_data)):
            real_index = len(history_data) - 1 - idx
            status = ticket.get("status", "PENDING")
            status_icon = "🟢" if status == "WON" else ("🔴" if status == "LOST" else "🟡")

            with st.expander(f"{status_icon} {ticket['name']} — Target Odds: {ticket['total_odds']:.2f} [{status}]"):
                st.write("**Legs:**")
                for leg in ticket["legs"]:
                    result_icon = {"WON": "🟢", "LOST": "🔴"}.get(leg.get("result", "PENDING"), "🟡")
                    st.write(f"• {result_icon} {leg['match']}: **{leg['selection']}** ({leg.get('bookmaker_odds', 1.0):.2f})")

                if st.session_state.role == "admin":
                    st.write("---")
                    with st.form(key=f"settle_form_{real_index}"):
                        leg_inputs = []
                        for li, leg in enumerate(ticket["legs"]):
                            result_choice = st.selectbox(
                                f"Outcome for {leg['match']} — {leg['selection']}",
                                ["PENDING", "WON", "LOST"],
                                index=["PENDING", "WON", "LOST"].index(leg.get("result", "PENDING")),
                                key=f"res_{real_index}_{li}"
                            )
                            leg_inputs.append(result_choice)
                        if st.form_submit_button("💾 Save Leg Outcomes"):
                            for li, res in enumerate(leg_inputs):
                                history_data[real_index]["legs"][li]["result"] = res
                            history_data[real_index]["status"] = recompute_ticket_status(history_data[real_index]["legs"])
                            _atomic_write(HISTORY_FILE, history_data)
                            st.rerun()

with tab3:
    st.subheader("📊 Poisson Model Calibration & Edge Audit")
    history_data = load_history()

    all_legs = []
    for ticket in history_data:
        for leg in ticket.get("legs", []):
            res = leg.get("result")
            if res in ["WON", "LOST"]:
                all_legs.append({
                    "odds": leg.get("bookmaker_odds", 1.20),
                    "prob": leg.get("model_probability", 0.80),
                    "ev": leg.get("expected_value_pct", 0.05),
                    "won": 1 if res == "WON" else 0
                })

    if not all_legs:
        st.info("Settle individual legs in the History tab to review Poisson model calibration statistics.")
    else:
        df = pd.DataFrame(all_legs)
        total_legs = len(df)
        actual_win_rate = df["won"].mean() * 100
        projected_win_rate = df["prob"].mean() * 100
        avg_ev = df["ev"].mean() * 100

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Settled Legs Sample", total_legs)
        m2.metric("Actual Win Rate", f"{actual_win_rate:.1f}%")
        m3.metric("Poisson Expected Win Rate", f"{projected_win_rate:.1f}%")
        m4.metric("Average Model Edge", f"+{avg_ev:.1f}% EV")

        st.write("---")
        diff = actual_win_rate - projected_win_rate
        if diff >= 0:
            st.success(f"🎯 **Model Calibration Positive:** Realized win rate exceeds mathematical expectations by **+{diff:.1f}%**!")
        else:
            st.warning(f"⚠️ **Model Calibration Negative:** Realized win rate trails mathematical expectations by **{diff:.1f}%**.")

