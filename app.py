import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import streamlit as st
from supabase import create_client, Client
import plotly.express as px
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Real-Time Crypto Dashboard",
    page_icon="🚀",
    layout="wide"
)

# --- Configuration ---
def get_secret(secret_key, default=None):
    """Safely retrieves a secret, checking env vars then Streamlit secrets."""
    value = os.getenv(secret_key)
    if value is not None:
        return value
    if hasattr(st, 'secrets') and secret_key in st.secrets:
        return st.secrets[secret_key]
    return default

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

ENABLE_EMAIL_ALERTS = str(get_secret("ENABLE_EMAIL_ALERTS", "false")).lower() == 'true'
ENABLE_TELEGRAM_ALERTS = str(get_secret("ENABLE_TELEGRAM_ALERTS", "false")).lower() == 'true'

EMAIL_SENDER_ADDRESS, EMAIL_SENDER_PASSWORD, EMAIL_RECEIVER_ADDRESS = (
    get_secret("EMAIL_SENDER_ADDRESS"), get_secret("EMAIL_SENDER_PASSWORD"), get_secret("EMAIL_RECEIVER_ADDRESS")
)
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = get_secret("TELEGRAM_BOT_TOKEN"), get_secret("TELEGRAM_CHAT_ID")

# API and Alerting Configuration
PRICE_DROP_ALERT_PERCENTAGE = -5.0
VOLUME_SPIKE_ALERT_PERCENTAGE = 50.0
ALERT_TIMEFRAME_HOURS = 1.0

# --- Database Connection ---
# Use st.cache_resource to only create the connection once
@st.cache_resource
def get_supabase_client():
    """Creates and returns a Supabase client, handling potential errors."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Supabase URL or Key is not configured. Please set SUPABASE_URL and SUPABASE_KEY in your secrets.")
        return None
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Test connection by fetching a small amount of data
        client.table('coin_price_data').select('id').limit(1).execute()
        return client
    except Exception as e:
        st.error(f"Supabase connection failed: {e}. Please verify your Supabase URL and Key.")
        return None

# --- Notification Functions ---
def send_email_alert(subject, body):
    """Sends an email alert."""
    # Use the user's email if provided, otherwise fall back to the default receiver.
    user_email = st.session_state.get('user_email', '').strip()
    recipient = user_email if user_email else EMAIL_RECEIVER_ADDRESS

    if not all([EMAIL_SENDER_ADDRESS, EMAIL_SENDER_PASSWORD, recipient]):
        st.warning("Email credentials not fully configured. Skipping email alert.")
        return

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_SENDER_ADDRESS
    msg['To'] = recipient

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER_ADDRESS, EMAIL_SENDER_PASSWORD)
            server.send_message(msg)
            print("📧 Email alert sent successfully.")
    except Exception as e:
        st.error(f"Failed to send email alert: {e}")

def send_telegram_alert(message):
    """Sends a message to a Telegram chat."""
    # Use the user's chat ID if provided, otherwise fall back to the default.
    user_chat_id = st.session_state.get('user_telegram_id', '').strip()
    chat_id = user_chat_id if user_chat_id else TELEGRAM_CHAT_ID

    if not all([TELEGRAM_BOT_TOKEN, chat_id]):
        st.warning("Telegram credentials not fully configured. Skipping Telegram alert.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("💬 Telegram alert sent successfully.")
    except Exception as e:
        st.error(f"Failed to send Telegram alert: {e}")

def send_alert(message):
    """Dispatches an alert to all configured channels."""
    st.toast(message) # Always show a toast in the app
    if st.session_state.get('email_alerts_enabled', False):
        send_email_alert("Crypto Price Alert!", message)
    if st.session_state.get('telegram_alerts_enabled', False):
        send_telegram_alert(message)

# --- Initialize Connection ---
supabase_client = get_supabase_client()

# --- Data Loading Functions ---
# Use st.cache_data to cache the data itself. It will only rerun if the input (ttl) changes.
# ttl = Time To Live. This clears the cache every 60 seconds, forcing a data refresh.
@st.cache_data(ttl=60)
def load_price_data(_client: Client):
    """Loads historical price data from the database."""
    if _client is None:
        return pd.DataFrame()
    try:
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        response = _client.table('coin_price_data').select('*').gte('ingestion_timestamp', thirty_days_ago).order('ingestion_timestamp', desc=False).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['ingestion_timestamp'] = pd.to_datetime(df['ingestion_timestamp'])
        return df
    except Exception as e:
        st.error(f"Failed to load price data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_latest_data(_client: Client):
    """Loads the most recent entry for each coin."""
    if _client is None:
        return pd.DataFrame()
    try:
        # Call the PostgreSQL function we created
        response = _client.rpc('get_latest_coin_data', {}).execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Failed to load latest data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_alert_logs(_client: Client):
    """Loads alert and error logs from the database."""
    if _client is None:
        return pd.DataFrame()
    # This table might not exist if no errors have occurred yet.
    # We will handle the error gracefully.
    try:
        response = _client.table('api_error_logs').select('*').order('timestamp', desc=True).execute()
        return pd.DataFrame(response.data)
    except Exception:
        # If the table doesn't exist, just return an empty DataFrame.
        return pd.DataFrame()

# --- Alerting Logic ---
def check_market_cap_overtakes(new_data_df: pd.DataFrame, _client: Client):
    """Compares the new market cap ranking with the previous one and alerts on any upward movement."""
    try:
        # Get the previous latest records for comparison
        response = _client.rpc('get_latest_coin_data', {}).execute()
        last_market_caps_df = pd.DataFrame(response.data)

        if last_market_caps_df.empty:
            print("ℹ️ Not enough historical data to check for market cap overtakes.")
            return

        # Establish the old and new rankings
        old_ranking_df = last_market_caps_df.sort_values(by='market_cap', ascending=False).reset_index(drop=True)
        new_ranking_df = new_data_df[['coin_id', 'name']].copy().reset_index() # The index is the new rank

        # Create a map of coin_id to its old rank for easy lookup
        old_rank_map = {row.coin_id: index for index, row in old_ranking_df.iterrows()}

        # Compare new ranks to old ranks
        for _, new_row in new_ranking_df.iterrows():
            coin_id = new_row['coin_id']
            new_rank = new_row['index']
            old_rank = old_rank_map.get(coin_id)

            if old_rank is not None and new_rank < old_rank:
                coin_name = new_row['name']
                overtaken_coin_id = old_ranking_df.iloc[new_rank]['coin_id']
                overtaken_coin_name = new_ranking_df.query(f"coin_id == '{overtaken_coin_id}'")['name'].iloc[0]
                send_alert(f"🚀 MARKET CAP ALERT: {coin_name} (now #{new_rank + 1}) has overtaken {overtaken_coin_name} (was #{new_rank + 1})!")
    except Exception as e:
        st.warning(f"Could not check market cap overtakes: {e}")

def check_price_volume_alerts(new_data_df: pd.DataFrame, _client: Client):
    """Checks for price drops or volume spikes against data from a configurable timeframe."""
    try:
        lookback_timestamp = (datetime.now(timezone.utc) - timedelta(hours=ALERT_TIMEFRAME_HOURS)).isoformat()

        for _, row in new_data_df.iterrows():
            coin_id = row['coin_id']
            current_price = row['current_price']
            current_volume = row['total_volume']

            # Get the most recent record from *before* the lookback period
            response = _client.table('coin_price_data') \
                .select('current_price, total_volume') \
                .eq('coin_id', coin_id) \
                .lte('ingestion_timestamp', lookback_timestamp) \
                .order('ingestion_timestamp', desc=True) \
                .limit(1) \
                .execute()

            if response.data:
                baseline_record = response.data[0]
                last_price = baseline_record.get('current_price')
                last_volume = baseline_record.get('total_volume')

                # 1. Check for significant price drop
                if last_price and last_price > 0:
                    price_change_pct = ((current_price - last_price) / last_price) * 100
                    if price_change_pct <= PRICE_DROP_ALERT_PERCENTAGE:
                        send_alert(f"🚨 PRICE DROP: {coin_id.upper()} dropped by {price_change_pct:.2f}% to ${current_price:,.2f} in the last {ALERT_TIMEFRAME_HOURS}h.")

                # 2. Check for sudden volume spike
                if last_volume and last_volume > 0:
                    volume_change_pct = ((current_volume - last_volume) / last_volume) * 100
                    if volume_change_pct >= VOLUME_SPIKE_ALERT_PERCENTAGE:
                        send_alert(f"📈 VOLUME SPIKE: {coin_id.upper()} volume up by {volume_change_pct:.2f}% in the last {ALERT_TIMEFRAME_HOURS}h.")
            
            # 3. Check for 24h percentage change (from API)
            price_change_24h = row.get('price_change_percentage_24h')
            if price_change_24h and price_change_24h <= -10.0:
                 send_alert(f"📉 24H CHANGE: {coin_id.upper()} is down {price_change_24h:.2f}% in the last 24 hours.")
    except Exception as e:
        st.warning(f"Could not check price/volume alerts: {e}")

# --- Pipeline Logic (Integrated into the app) ---
def run_pipeline_logic(_client: Client, force_run: bool = False):
    """Main function to fetch, process, store, and alert on crypto data."""
    if not _client:
        st.error("Pipeline logic skipped due to database connection failure.")
        return "Pipeline Failed", False

    # Manual Throttling (replacing @st.cache_data to avoid CacheReplayClosureError)
    if not force_run:
        last_run_ts = st.session_state.get('pipeline_last_run_ts')
        if last_run_ts:
            last_run = datetime.fromisoformat(last_run_ts)
            if (datetime.now(timezone.utc) - last_run).total_seconds() < 300:
                return f"Pipeline last run at {last_run.strftime('%H:%M:%S')} (Cached)", False

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": "bitcoin,ethereum,solana,cardano,dogecoin", "order": "market_cap_desc"}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        df = pd.json_normalize(data)
        df['ingestion_timestamp'] = datetime.now(timezone.utc).isoformat()

        # --- Data Validation ---
        required_cols = ['id', 'current_price', 'market_cap', 'total_volume']
        if not all(col in df.columns for col in required_cols) or df[required_cols].isnull().values.any():
            raise ValueError("Invalid data from API: missing columns or null values.")

        # --- Column Renaming ---
        df = df[['id', 'symbol', 'name', 'current_price', 'market_cap', 'total_volume', 'price_change_percentage_24h', 'last_updated', 'ingestion_timestamp']]
        df.columns = ['coin_id', 'symbol', 'name', 'current_price', 'market_cap', 'total_volume', 'price_change_percentage_24h', 'last_updated', 'ingestion_timestamp']

        # --- Run Full Alert Checks ---
        check_market_cap_overtakes(df, _client)
        check_price_volume_alerts(df, _client)
        
        # Append new data to the database table
        records_to_insert = df.to_dict(orient='records')
        _client.table('coin_price_data').insert(records_to_insert).execute()
        st.session_state['pipeline_last_run_ts'] = datetime.now(timezone.utc).isoformat()
        return f"Pipeline run successful at {datetime.now(timezone.utc).strftime('%H:%M:%S')}", True

    except requests.exceptions.RequestException as e:
        error_details = {"error_message": str(e), "source": "CoinGecko API", "timestamp": datetime.now(timezone.utc).isoformat()}
        _client.table('api_error_logs').insert(error_details).execute()
        return f"API Error: {e}", True
    except Exception as e:
        return f"An unexpected Error occurred in pipeline: {e}", True


# --- Dashboard UI ---
st.title("🚀 Real-Time Crypto Price Dashboard")
st.markdown(f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")

# Run the auto-refresh component every 65 seconds (65000 milliseconds)
st_autorefresh(interval=65 * 1000, key="data_refresher")

# --- Initialize Session State for Alert Toggles ---
if 'email_alerts_enabled' not in st.session_state:
    st.session_state.email_alerts_enabled = ENABLE_EMAIL_ALERTS
if 'telegram_alerts_enabled' not in st.session_state:
    st.session_state.telegram_alerts_enabled = ENABLE_TELEGRAM_ALERTS
if 'user_email' not in st.session_state:
    st.session_state.user_email = "" # Initialize as empty
if 'user_telegram_id' not in st.session_state:
    st.session_state.user_telegram_id = "" # Initialize as empty

# --- Sidebar and Pipeline Execution ---
st.sidebar.title("⚙️ Pipeline Control")

# Default to a throttled run
force_pipeline = False

# Add a button to force the run
if st.sidebar.button("🔄 Refresh Data Now"):
    force_pipeline = True
    st.toast("Requesting immediate data refresh...")

# Trigger the pipeline logic.
pipeline_status, pipeline_ran = run_pipeline_logic(supabase_client, force_run=force_pipeline)
st.sidebar.write(pipeline_status)

# If the pipeline was forced and ran, we need to clear caches and rerun the script
if force_pipeline and pipeline_ran:
    load_price_data.clear()
    load_latest_data.clear()
    load_alert_logs.clear()
    st.rerun()

# Load data (will be fresh if caches were just cleared)
price_df = load_price_data(supabase_client)
latest_df = load_latest_data(supabase_client)
logs_df = load_alert_logs(supabase_client)

if price_df.empty or latest_df.empty:
    st.warning("No data found in the database. Is the data pipeline running?")
else:
    # --- Helper functions for UI masking ---
    def mask_email(email):
        """Masks an email address for display."""
        if not email or '@' not in email:
            return "your.email@example.com"
        local_part, domain = email.split('@')
        if len(local_part) <= 1:
            return f"{local_part[0]}***@{domain}"
        return f"{local_part[:1]}***@{domain}"

    def mask_telegram_id(chat_id):
        """Masks a Telegram chat ID for display."""
        if not chat_id or not str(chat_id).isdigit():
            return "Your Chat ID"
        chat_id_str = str(chat_id)
        if len(chat_id_str) <= 4:
            return f"{chat_id_str[0]}***"
        return f"{chat_id_str[:0]}***{chat_id_str[-1:]}"

    # --- Tabbed Layout ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Price Analysis", "🚨 System Logs", "🔔 Alert Management"])

    with tab1:
        # --- Overview Tab ---
        st.subheader("Latest Prices")
        
        # Format the latest data for better display
        latest_df_display = latest_df.copy()
        latest_df_display['current_price'] = latest_df_display['current_price'].apply(lambda x: f"${x:,.2f}")
        latest_df_display['market_cap'] = latest_df_display['market_cap'].apply(lambda x: f"${x:,.0f}")
        latest_df_display['total_volume'] = latest_df_display['total_volume'].apply(lambda x: f"${x:,.0f}")
        latest_df_display['price_change_percentage_24h'] = latest_df_display['price_change_percentage_24h'].apply(lambda x: f"{x:.2f}%")
        
        st.dataframe(
            latest_df_display.set_index('name'),
            width="stretch"
        )

        st.subheader("Market Cap Distribution")
        pie_fig = px.pie(latest_df, values='market_cap', names='name', title='Market Cap Distribution')
        st.plotly_chart(pie_fig, width="stretch")

    with tab2:
        # --- Price Analysis Tab ---
        st.subheader("Price History")
        coin_options = price_df['name'].unique()
        selected_coin = st.selectbox("Select a coin to visualize:", coin_options)

        if selected_coin:
            chart_df = price_df[price_df['name'] == selected_coin]

            # --- Date Range Selector ---
            # Get the min and max dates from the data for the selected coin
            min_date = chart_df['ingestion_timestamp'].min().date()
            max_date = chart_df['ingestion_timestamp'].max().date()

            date_range = st.date_input(
                "Select date range to analyze:",
                value=(min_date, max_date), # Default range
                min_value=min_date,
                max_value=max_date,
                format="YYYY-MM-DD"
            )

            # Filter the dataframe based on the selected date range
            if len(date_range) == 2:
                start_date, end_date = date_range
                mask = (chart_df['ingestion_timestamp'].dt.date >= start_date) & (chart_df['ingestion_timestamp'].dt.date <= end_date)
                chart_df = chart_df.loc[mask]
            
            # --- Chart Type Selector ---
            st.subheader("Chart Options")
            chart_type = st.radio("Select Chart Type:", ["Line Chart", "Candlestick Chart"], horizontal=True)


            # --- Moving Average Selector ---
            ma_periods = [5, 10, 20, 50]
            selected_mas = st.multiselect(
                "Add Moving Average (MA) lines:",
                options=ma_periods,
                default=[]
            )
            
            # --- Bollinger Bands Selector ---
            bb_period = 20
            bb_std = 2
            show_bb = st.checkbox(f"Add Bollinger Bands ({bb_period}-period, {bb_std} std dev)")


            # --- Summary Statistics ---
            if not chart_df.empty:
                st.subheader("Summary for Selected Period")
                max_price = chart_df['current_price'].max()
                min_price = chart_df['current_price'].min()
                
                first_price = chart_df['current_price'].iloc[0]
                last_price = chart_df['current_price'].iloc[-1]
                
                pct_change = ((last_price - first_price) / first_price) * 100 if first_price != 0 else 0
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Highest Price", f"${max_price:,.2f}")
                col2.metric("Lowest Price", f"${min_price:,.2f}")
                col3.metric("Period Change", f"{pct_change:.2f}%")

            # --- Chart Rendering ---
            st.subheader(f"{chart_type}")
            if chart_type == "Line Chart":
                # Calculate indicators on raw data
                for period in selected_mas:
                    if len(chart_df) >= period: chart_df[f'MA_{period}'] = chart_df['current_price'].rolling(window=period).mean()
                if show_bb and len(chart_df) >= bb_period:
                    chart_df['BB_Middle'] = chart_df['current_price'].rolling(window=bb_period).mean()
                    rolling_std = chart_df['current_price'].rolling(window=bb_period).std()
                    chart_df['BB_Upper'] = chart_df['BB_Middle'] + (rolling_std * bb_std)
                    chart_df['BB_Lower'] = chart_df['BB_Middle'] - (rolling_std * bb_std)

                fig = px.line(chart_df, x='ingestion_timestamp', y='current_price', title=f'{selected_coin} Price Over Time', markers=True)
                
                # Add traces for indicators
                for period in selected_mas:
                    if f'MA_{period}' in chart_df.columns: fig.add_scatter(x=chart_df['ingestion_timestamp'], y=chart_df[f'MA_{period}'], mode='lines', name=f'{period}-Period MA')
                if show_bb and 'BB_Middle' in chart_df.columns:
                    fig.add_scatter(x=chart_df['ingestion_timestamp'], y=chart_df['BB_Upper'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Upper')
                    fig.add_scatter(x=chart_df['ingestion_timestamp'], y=chart_df['BB_Middle'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Middle')
                    fig.add_scatter(x=chart_df['ingestion_timestamp'], y=chart_df['BB_Lower'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Lower')

            elif chart_type == "Candlestick Chart":
                if not chart_df.empty:
                    # Resample data to daily OHLC
                    ohlc_df = chart_df.set_index('ingestion_timestamp')['current_price'].resample('D').ohlc()
                    ohlc_df = ohlc_df.dropna() # Remove days with no data

                    fig = go.Figure(data=[go.Candlestick(x=ohlc_df.index,
                                    open=ohlc_df['open'], high=ohlc_df['high'],
                                    low=ohlc_df['low'], close=ohlc_df['close'],
                                    name='Price')])

                    # Calculate indicators on resampled (daily close) data
                    for period in selected_mas:
                        if len(ohlc_df) >= period: ohlc_df[f'MA_{period}'] = ohlc_df['close'].rolling(window=period).mean()
                    if show_bb and len(ohlc_df) >= bb_period:
                        ohlc_df['BB_Middle'] = ohlc_df['close'].rolling(window=bb_period).mean()
                        rolling_std = ohlc_df['close'].rolling(window=bb_period).std()
                        ohlc_df['BB_Upper'] = ohlc_df['BB_Middle'] + (rolling_std * bb_std)
                        ohlc_df['BB_Lower'] = ohlc_df['BB_Middle'] - (rolling_std * bb_std)

                    # Add traces for indicators
                    for period in selected_mas:
                        if f'MA_{period}' in ohlc_df.columns: fig.add_scatter(x=ohlc_df.index, y=ohlc_df[f'MA_{period}'], mode='lines', name=f'{period}-Day MA')
                    if show_bb and 'BB_Middle' in ohlc_df.columns:
                        fig.add_scatter(x=ohlc_df.index, y=ohlc_df['BB_Upper'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Upper')
                        fig.add_scatter(x=ohlc_df.index, y=ohlc_df['BB_Middle'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Middle')
                        fig.add_scatter(x=ohlc_df.index, y=ohlc_df['BB_Lower'], mode='lines', line=dict(color='gray', dash='dash'), name='BB Lower')

                    fig.update_layout(title=f'{selected_coin} Daily Candlestick Chart', xaxis_title="Date", yaxis_title="Price (USD)")
                else:
                    fig = go.Figure() # Empty figure if no data

            fig.update_layout(xaxis_title="Time", yaxis_title="Price (USD)")
            st.plotly_chart(fig, width="stretch")

            # --- Filtered Data Table ---
            st.subheader("Filtered Data View")

            # Add a download button for the raw filtered data
            csv = chart_df.to_csv(index=False).encode('utf-8')
            st.download_button(
               label="Download Data as CSV",
               data=csv,
               file_name=f'{selected_coin}_price_data.csv',
               mime='text/csv',
            )

            if not chart_df.empty:
                # Select and format a subset of columns for better readability
                display_df = chart_df[['ingestion_timestamp', 'current_price', 'market_cap', 'total_volume']].copy()
                display_df['current_price'] = display_df['current_price'].apply(lambda x: f"${x:,.2f}")
                display_df['market_cap'] = display_df['market_cap'].apply(lambda x: f"${x:,.0f}")
                display_df['total_volume'] = display_df['total_volume'].apply(lambda x: f"${x:,.0f}")
                display_df = display_df.set_index('ingestion_timestamp')

                # --- Pagination Logic ---
                rows_per_page = 15
                total_rows = len(display_df)
                total_pages = (total_rows // rows_per_page) + (1 if total_rows % rows_per_page > 0 else 0)

                col1, col2 = st.columns([1, 3])
                with col1:
                    page_number = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
                with col2:
                    st.caption(f"Displaying page {page_number} of {total_pages} ({total_rows} total records)")

                start_idx = (page_number - 1) * rows_per_page
                end_idx = start_idx + rows_per_page
                paginated_df = display_df.iloc[start_idx:end_idx]
                
                st.dataframe(paginated_df, width="stretch")


    with tab3:
        # --- System Logs Tab ---
        st.subheader("Alert & Error Logs")
        if not logs_df.empty:
            st.dataframe(
                logs_df.set_index('id'),
                width="stretch"
            )
        else:
            st.info("No alerts or errors have been logged yet. Everything looks good!")

    with tab4:
        # --- Alert Management Tab ---
        st.header("🔔 Configure Your Personal Alerts on Price & Volume spikes")
        st.write("Enable and configure email or Telegram alerts. Your settings are saved for your current session.")

        st.subheader("Email Alerts")
        st.toggle("Enable Email Alerts", key='email_alerts_enabled')
        st.text_input("Your Email Address", key='user_email', placeholder=mask_email(EMAIL_RECEIVER_ADDRESS), disabled=not st.session_state.email_alerts_enabled)

        st.subheader("Telegram Alerts")
        st.toggle("Enable Telegram Alerts", key='telegram_alerts_enabled')
        st.text_input("Your Telegram Chat ID", key='user_telegram_id', placeholder=mask_telegram_id(TELEGRAM_CHAT_ID), disabled=not st.session_state.telegram_alerts_enabled)
        st.caption("Note: To get your Chat ID, message the `@userinfobot` on Telegram.")
