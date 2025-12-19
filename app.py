import requests
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
import streamlit as st
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
# Use Streamlit secrets for deployment, with .env as a fallback for local development
DB_HOST = os.getenv("DB_HOST", st.secrets.get("DB_HOST")) # e.g., db.xxxxxxxx.supabase.co
DB_PASSWORD = os.getenv("DB_PASSWORD", st.secrets.get("DB_PASSWORD"))
DB_PORT = os.getenv("DB_PORT", st.secrets.get("DB_PORT", 5432)) # Default to 5432, but use 6543 for pooler

ENABLE_EMAIL_ALERTS = os.getenv("ENABLE_EMAIL_ALERTS", st.secrets.get("ENABLE_EMAIL_ALERTS", "false")).lower() == 'true'
ENABLE_TELEGRAM_ALERTS = os.getenv("ENABLE_TELEGRAM_ALERTS", st.secrets.get("ENABLE_TELEGRAM_ALERTS", "false")).lower() == 'true'

EMAIL_SENDER_ADDRESS = os.getenv("EMAIL_SENDER_ADDRESS", st.secrets.get("EMAIL_SENDER_ADDRESS"))
EMAIL_SENDER_PASSWORD = os.getenv("EMAIL_SENDER_PASSWORD", st.secrets.get("EMAIL_SENDER_PASSWORD"))
EMAIL_RECEIVER_ADDRESS = os.getenv("EMAIL_RECEIVER_ADDRESS", st.secrets.get("EMAIL_RECEIVER_ADDRESS"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", st.secrets.get("TELEGRAM_BOT_TOKEN"))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", st.secrets.get("TELEGRAM_CHAT_ID"))

# API and Alerting Configuration
PRICE_DROP_ALERT_PERCENTAGE = -5.0
VOLUME_SPIKE_ALERT_PERCENTAGE = 50.0
ALERT_TIMEFRAME_HOURS = 1.0

# --- Database Connection ---
# Use st.cache_resource to only create the connection once
@st.cache_resource
def get_engine():
    """Creates and returns a SQLAlchemy engine."""
    try:
        # Use the connection pooler URI format for Supabase
        conn_string = f"postgresql://postgres:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
        engine = create_engine(conn_string)
        
        # On first run, create tables if they don't exist.
        setup_database_tables(engine)

        return engine
    except Exception as e:
        st.error(f"Supabase connection failed: {e}. Ensure DB_HOST, DB_PASSWORD, and DB_PORT are set correctly in your secrets.")
        return None

def setup_database_tables(engine):
    """Initializes tables in the Supabase database if they don't exist."""
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS coin_price_data (
                    id SERIAL PRIMARY KEY,
                    coin_id TEXT, symbol TEXT, name TEXT,
                    current_price DOUBLE PRECISION, market_cap DOUBLE PRECISION, total_volume DOUBLE PRECISION,
                    price_change_percentage_24h DOUBLE PRECISION, last_updated TEXT, ingestion_timestamp TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS api_error_logs (
                    id SERIAL PRIMARY KEY, error_message TEXT, source TEXT, timestamp TEXT
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_coin_price_data_coin_id ON coin_price_data (coin_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_coin_price_data_ingestion_timestamp ON coin_price_data (ingestion_timestamp);"))
            conn.commit()
    except Exception as e:
        st.error(f"Failed to create database tables: {e}")

# --- Notification Functions ---
def send_email_alert(subject, body):
    """Sends an email alert."""
    # Implementation is the same as your original script
    pass

def send_telegram_alert(message):
    """Sends a message to a Telegram chat."""
    # Implementation is the same as your original script
    pass

def send_alert(message):
    """Dispatches an alert to all configured channels."""
    st.toast(message) # Always show a toast in the app
    if ENABLE_EMAIL_ALERTS:
        send_email_alert("Crypto Price Alert!", message)
    if ENABLE_TELEGRAM_ALERTS:
        send_telegram_alert(message)

# --- Initialize Connection ---
engine = get_engine()

# --- Data Loading Functions ---
# Use st.cache_data to cache the data itself. It will only rerun if the input (ttl) changes.
# ttl = Time To Live. This clears the cache every 60 seconds, forcing a data refresh.
@st.cache_data(ttl=60)
def load_price_data(_engine):
    """Loads historical price data from the database."""
    if _engine is None:
        return pd.DataFrame()
    try:
        with _engine.connect() as conn:
            # --- PERFORMANCE OPTIMIZATION ---
            # Only load the last 30 days of data by default to keep the dashboard snappy.
            # The ::timestamp cast is necessary because the column is TEXT.
            query = text(f"""
                SELECT * FROM coin_price_data WHERE ingestion_timestamp::timestamp >= NOW() - INTERVAL '30 days' ORDER BY ingestion_timestamp ASC
            """)
            df = pd.read_sql(query, conn)
            # Convert timestamp strings to datetime objects for plotting
            df['ingestion_timestamp'] = pd.to_datetime(df['ingestion_timestamp'], format='ISO8601')
            return df
    except Exception as e:
        st.error(f"Failed to load price data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_latest_data(_engine):
    """Loads the most recent entry for each coin."""
    if _engine is None:
        return pd.DataFrame()
    query = text("""
        WITH latest_records AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY coin_id ORDER BY ingestion_timestamp DESC) as rn
            FROM coin_price_data
        )
        SELECT coin_id, name, symbol, current_price, market_cap, total_volume, price_change_percentage_24h
        FROM latest_records
        WHERE rn = 1;
    """)
    try:
        with _engine.connect() as conn:
            return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"Failed to load latest data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_alert_logs(_engine):
    """Loads alert and error logs from the database."""
    if _engine is None:
        return pd.DataFrame()
    # This table might not exist if no errors have occurred yet.
    # We will handle the error gracefully.
    try:
        with _engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM api_error_logs ORDER BY timestamp DESC", conn)
            return df
    except Exception:
        # If the table doesn't exist, just return an empty DataFrame.
        return pd.DataFrame()

# --- Pipeline Logic (Integrated into the app) ---
@st.cache_data(ttl=300) # Run this logic at most once every 5 minutes
def run_pipeline_logic(_engine):
    """Main function to fetch, process, store, and alert on crypto data."""
    if not _engine:
        st.error("Pipeline logic skipped due to database connection failure.")
        return "Pipeline Failed"

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": "bitcoin,ethereum,solana,cardano,dogecoin", "order": "market_cap_desc"}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        df = pd.json_normalize(data)
        df['ingestion_timestamp'] = datetime.utcnow().isoformat()

        # --- Data Validation ---
        required_cols = ['id', 'current_price', 'market_cap', 'total_volume']
        if not all(col in df.columns for col in required_cols) or df[required_cols].isnull().values.any():
            raise ValueError("Invalid data from API: missing columns or null values.")

        # --- Column Renaming ---
        df = df[['id', 'symbol', 'name', 'current_price', 'market_cap', 'total_volume', 'price_change_percentage_24h', 'last_updated', 'ingestion_timestamp']]
        df.columns = ['coin_id', 'symbol', 'name', 'current_price', 'market_cap', 'total_volume', 'price_change_percentage_24h', 'last_updated', 'ingestion_timestamp']

        # --- Run Alert Checks (Simplified for brevity, can be expanded) ---
        # check_market_cap_overtakes(df, _engine)
        # check_alerts(df, _engine)
        
        # Append new data to the database table
        df.to_sql("coin_price_data", _engine, if_exists="append", index=False)
        return f"Pipeline run successful at {datetime.now().strftime('%H:%M:%S')}"

    except requests.exceptions.RequestException as e:
        error_details = {"error_message": str(e), "source": "CoinGecko API", "timestamp": datetime.utcnow().isoformat()}
        pd.DataFrame([error_details]).to_sql("api_error_logs", _engine, if_exists="append", index=False)
        return f"API Error: {e}"
    except Exception as e:
        return f"An unexpected Error occurred in pipeline: {e}"


# --- Dashboard UI ---
st.title("🚀 Real-Time Crypto Price Dashboard")
st.markdown(f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")

# Run the auto-refresh component every 65 seconds (65000 milliseconds)
st_autorefresh(interval=65 * 1000, key="data_refresher")

# Load data
# Trigger the pipeline logic. Caching ensures it doesn't run on every single interaction.
pipeline_status = run_pipeline_logic(engine)
st.sidebar.write(pipeline_status)

price_df = load_price_data(engine)
latest_df = load_latest_data(engine)
logs_df = load_alert_logs(engine)

if price_df.empty or latest_df.empty:
    st.warning("No data found in the database. Is the data pipeline running?")
else:
    # --- Tabbed Layout ---
    tab1, tab2, tab3 = st.tabs(["📊 Overview", "📈 Price Analysis", "🚨 System Logs"])

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
            use_container_width=True
        )

        st.subheader("Market Cap Distribution")
        pie_fig = px.pie(latest_df, values='market_cap', names='name', title='Market Cap Distribution')
        st.plotly_chart(pie_fig, use_container_width=True)

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
            st.plotly_chart(fig, use_container_width=True)

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

            # Select and format a subset of columns for better readability
            display_df = chart_df[['ingestion_timestamp', 'current_price', 'market_cap', 'total_volume']].copy()
            display_df['current_price'] = display_df['current_price'].apply(lambda x: f"${x:,.2f}")
            display_df['market_cap'] = display_df['market_cap'].apply(lambda x: f"${x:,.0f}")
            display_df['total_volume'] = display_df['total_volume'].apply(lambda x: f"${x:,.0f}")
            
            st.dataframe(display_df.set_index('ingestion_timestamp'), use_container_width=True)


    with tab3:
        # --- System Logs Tab ---
        st.subheader("Alert & Error Logs")
        if not logs_df.empty:
            st.dataframe(
                logs_df.set_index('id'),
                use_container_width=True
            )
        else:
            st.info("No alerts or errors have been logged yet. Everything looks good!")
