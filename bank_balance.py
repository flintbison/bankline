import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import altair as alt

st.set_page_config(page_title="Balance Forecaster", layout="wide")

DATA_FILE = "cashflow_data.json"

# ---------------------------
# JSON Persistence
# ---------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"bills": [], "income": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(
            {"bills": st.session_state.bills, "income": st.session_state.income},
            f,
            default=str,
        )

# ---------------------------
# Helpers
# ---------------------------
def generate_recurring_events(start_date, end_date, amount, freq):
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        if freq == "Daily":
            current += timedelta(days=1)
        elif freq == "Weekly":
            current += timedelta(weeks=1)
        elif freq == "Monthly":
            month = current.month
            year = current.year
            if month == 12:
                current = current.replace(year=year + 1, month=1)
            else:
                current = current.replace(month=month + 1)
        elif freq == "Yearly":
            try:
                current = current.replace(year=current.year + 1)
            except ValueError:
                # Handles Feb 29 -> Feb 28 for non-leap years
                current = current.replace(month=2, day=28, year=current.year + 1)
    return pd.DataFrame({"date": dates, "amount": amount})

def project_balance(start_balance, events, start_date, end_date):
    timeline = pd.DataFrame({"date": pd.date_range(start_date, end_date)})
    timeline["date"] = pd.to_datetime(timeline["date"]).dt.normalize()
    timeline["balance"] = start_balance
    if not events.empty:
        events_local = events.copy()
        events_local["date"] = pd.to_datetime(events_local["date"]).dt.normalize()
        daily = events_local.groupby("date")["amount"].sum().reset_index()
        timeline = timeline.merge(daily, on="date", how="left")
        timeline["amount"] = timeline["amount"].fillna(0)
    else:
        timeline["amount"] = 0
    timeline["balance"] = start_balance + timeline["amount"].cumsum()
    return timeline

# ---------------------------
# Load Data into Session State
# ---------------------------
if "bills" not in st.session_state:
    data = load_data()
    st.session_state.bills = data["bills"]
    st.session_state.income = data["income"]

# ---------------------------
# Sidebar Inputs
# ---------------------------
st.sidebar.header("Add Recurring Cash Flow")
flow_type = st.sidebar.selectbox("Type", ["Bill (expense)", "Income"])
name = st.sidebar.text_input("Name")
amount = st.sidebar.number_input("Amount (negative for bills automatically applied)", value=0.0)
if flow_type == "Bill (expense)" and amount > 0:
    amount = -abs(amount)
frequency = st.sidebar.selectbox("Frequency", ["Daily", "Weekly", "Monthly", "Yearly"])
start_date_input = st.sidebar.date_input("Start Date", datetime.today())
end_date_input = st.sidebar.date_input("End Date", datetime.today() + timedelta(days=180))

if st.sidebar.button("Add"):
    entry = {
        "name": name,
        "amount": amount,
        "frequency": frequency,
        "start_date": str(start_date_input),
        "end_date": str(end_date_input)
    }
    if flow_type == "Bill (expense)":
        st.session_state.bills.append(entry)
    else:
        st.session_state.income.append(entry)
    save_data()

# ---------------------------
# Main Layout
# ---------------------------
st.title("📊 Balance Forecast App")
start_balance = st.number_input("Current Balance", value=0.0)
forecast_days = st.slider("Project ahead (days)", 30, 730, 180)
start_date = datetime.today()
end_date = start_date + timedelta(days=forecast_days)
tabs = st.tabs(["Bills", "Income", "Projection"])

# ---------------------------
# Bills Tab
# ---------------------------
with tabs[0]:
    st.subheader("Recurring Bills")
    if st.session_state.bills:
        bill_df = pd.DataFrame(st.session_state.bills)
        st.table(bill_df)
        remove = st.selectbox("Remove bill", ["None"] + bill_df["name"].tolist())
        if st.button("Delete Bill") and remove != "None":
            st.session_state.bills = [b for b in st.session_state.bills if b["name"] != remove]
            save_data()
    else:
        st.info("No bills added yet.")

# ---------------------------
# Income Tab
# ---------------------------
with tabs[1]:
    st.subheader("Recurring Income")
    if st.session_state.income:
        income_df = pd.DataFrame(st.session_state.income)
        st.table(income_df)
        remove = st.selectbox("Remove income", ["None"] + income_df["name"].tolist())
        if st.button("Delete Income") and remove != "None":
            st.session_state.income = [i for i in st.session_state.income if i["name"] != remove]
            save_data()
    else:
        st.info("No income added yet.")

# ---------------------------
# Projection Tab
# ---------------------------
with tabs[2]:
    st.subheader("Balance Projection")

    event_frames = []

    # Bills
    for item in st.session_state.bills:
        df = generate_recurring_events(
            pd.to_datetime(item["start_date"]),
            pd.to_datetime(item["end_date"]),
            item["amount"],
            item["frequency"]
        )
        df["type"] = "Bill"
        df["name"] = item.get("name", "")
        event_frames.append(df)

    # Income
    for item in st.session_state.income:
        df = generate_recurring_events(
            pd.to_datetime(item["start_date"]),
            pd.to_datetime(item["end_date"]),
            item["amount"],
            item["frequency"]
        )
        df["type"] = "Income"
        df["name"] = item.get("name", "")
        event_frames.append(df)

    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame(columns=["date", "amount", "type", "name"])
    events["date"] = pd.to_datetime(events["date"]).dt.normalize()

    # Calculate projection
    timeline = project_balance(start_balance, events, start_date, end_date)

    # Merge timeline balance into events
    if not events.empty:
        events = events.merge(timeline[["date", "balance"]], on="date", how="left")

    # ---- Line chart ----
    line = (
        alt.Chart(timeline)
        .mark_line()
        .encode(
            x="date:T",
            y="balance:Q",
            color=alt.condition("datum.balance >= 0", alt.value("green"), alt.value("red"))
        )
    )

    # ---- Event markers ----
    if not events.empty:
        events["marker"] = events["type"].apply(lambda t: "▲" if t=="Income" else "▼")
        events["color"] = events["type"].apply(lambda t: "green" if t=="Income" else "red")
        points = (
            alt.Chart(events)
            .mark_text(dy=-10)
            .encode(
                x="date:T",
                y="balance:Q",
                text="marker:N",
                color=alt.Color("color:N", scale=None, legend=None),  # force color and remove legend
                tooltip=["name:N", "type:N", "amount:Q", "date:T", "balance:Q"]
            )
        )
        chart = line + points
    else:
        chart = line

    st.altair_chart(chart, use_container_width=True)
    st.write("Projected balances:")
    st.dataframe(timeline)

    min_balance = timeline["balance"].min()
    if min_balance < 0:
        st.error(f"⚠️ Your balance will go negative. Lowest point: {min_balance:.2f}")
    else:
        st.success("✔️ Your balance stays positive through this period!")
