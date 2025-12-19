# Real-Time Crypto Monitoring Dashboard

This project is a self-contained, cloud-native Streamlit application that provides real-time cryptocurrency monitoring, analysis, and personalized alerting. It fetches live data from the CoinGecko API, stores it in a Supabase PostgreSQL database, and presents it through a rich, interactive dashboard.

## Who is this for?

-   **Crypto Traders & Enthusiasts**: Monitor your favorite assets in real-time, analyze trends with technical indicators, and receive personalized alerts without needing to constantly watch the charts.
-   **Data Analysts & Students**: Explore a practical, end-to-end example of a modern data application, from API ingestion to cloud storage and interactive visualization.
-   **Developers**: Use this project as a robust template for building your own real-time data dashboards with Streamlit and a serverless database backend.

## Core Purposes

-   **Monitoring**: Get a live, at-a-glance overview of cryptocurrency prices, market caps, and 24-hour performance.
-   **Alerting**: Configure and receive personalized alerts for significant market events via Email or Telegram, freeing you from manual tracking.
-   **Analysis**: Dive deep into price history with interactive charts, moving averages, and Bollinger Bands to identify trends and patterns.
-   **Learning**: Serves as a comprehensive, real-world example of integrating external APIs, a cloud database, and an interactive web framework into a single, deployable application.

## Key Features

-   **Cloud-Native Architecture**: Designed from the ground up to run entirely on Streamlit Community Cloud, with no separate servers or schedulers needed.
-   **Persistent Cloud Storage**: Utilizes a free-tier Supabase PostgreSQL database for reliable and persistent data storage.
-   **Self-Contained Data Pipeline**: The application itself manages periodic data fetching using Streamlit's caching (`@st.cache_data`) and auto-refresh mechanisms.
-   **Personalized Alert Management**: A dedicated tab allows any user to enable alerts and direct them to their own Email address or Telegram Chat ID for the duration of their session.
-   **Rich Interactive Dashboard**:
    -   **Overview**: Live prices and market cap distribution pie chart.
    -   **Price Analysis**: Interactive Line and Candlestick charts with date range selectors.
    -   **Technical Indicators**: On-demand Moving Averages and Bollinger Bands.
    -   **Data Exploration**: Paginated data view with a CSV download option.
    -   **System Health**: A log viewer to monitor API errors.

## Application Architecture

The application operates as a single, cohesive unit deployed on Streamlit Community Cloud.

```mermaid
graph TD
    subgraph "User's Browser"
        USER[👤 User]
    end

    subgraph "Cloud Platform (Streamlit Community Cloud)"
        APP["🚀 Streamlit App (app.py)<br/>- UI Rendering<br/>- Data Caching<br/>- Alert Logic"]
    end
    subgraph "External Services"
        API["🌐 CoinGecko API"]
        DB["💾 Supabase DB (PostgreSQL)"]
        EMAIL["📧 Email (SMTP)"]
        TELEGRAM["💬 Telegram Bot API"]
    end

    USER <-->|Interacts with| APP
    APP -->|1. Fetch Data (every 5 mins)<br/>@st.cache_data(ttl=300)| API
    APP -->|2. Store Data<br/>supabase.table().insert()| DB
    APP -->|3. Load Data for Charts<br/>supabase.table().select()| DB
    APP -->|4. Send Alerts (if triggered)| EMAIL
    APP -->|4. Send Alerts (if triggered)| TELEGRAM

    classDef userStyle fill:#93c5fd,stroke:#3b82f6,stroke-width:2px
    classDef appStyle fill:#86efac,stroke:#22c55e,stroke-width:2px
    classDef serviceStyle fill:#fde047,stroke:#eab308,stroke-width:2px

    class USER userStyle
    class APP appStyle
    class API,DB,EMAIL,TELEGRAM serviceStyle
```

### 3. Set Up Environment and Install Dependencies
## Setup and Deployment

It is highly recommended to use a virtual environment.
### 1. Supabase Project Setup

```sh
# Create and activate a conda environment
conda create --name crypto-pipeline python=3.9
conda activate crypto-pipeline
1.  **Create a Project**: Go to Supabase and create a new project.
2.  **Run SQL Script**: In your new project, navigate to the **SQL Editor**, click **"New query"**, and run the following script **one time** to create the necessary tables and functions.

# Install required packages
pip install requests pandas sqlalchemy psycopg2-binary python-dotenv tenacity streamlit streamlit-autorefresh plotly
```
    ```sql
    -- Create the table for price data
    CREATE TABLE IF NOT EXISTS coin_price_data (
        id SERIAL PRIMARY KEY, coin_id TEXT, symbol TEXT, name TEXT,
        current_price DOUBLE PRECISION, market_cap DOUBLE PRECISION, total_volume DOUBLE PRECISION,
        price_change_percentage_24h DOUBLE PRECISION, last_updated TEXT, ingestion_timestamp TEXT
    );

### 4. Database Setup
    -- Create the table for API error logs
    CREATE TABLE IF NOT EXISTS api_error_logs (
        id SERIAL PRIMARY KEY, error_message TEXT, source TEXT, timestamp TEXT
    );

1.  Open your PostgreSQL client (e.g., `psql` or pgAdmin).
2.  Create a new database named `cryptoalerts`.
    -- Create indexes to speed up queries
    CREATE INDEX IF NOT EXISTS idx_coin_price_data_coin_id ON coin_price_data (coin_id);
    CREATE INDEX IF NOT EXISTS idx_coin_price_data_ingestion_timestamp ON coin_price_data (ingestion_timestamp);

    ```sql
    CREATE DATABASE "cryptoalerts";
    -- Create a function to get the latest record for each coin (for performance)
    CREATE OR REPLACE FUNCTION get_latest_coin_data()
    RETURNS SETOF coin_price_data AS $$
    BEGIN
        RETURN QUERY
        WITH latest_records AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY coin_id ORDER BY ingestion_timestamp DESC) as rn
            FROM coin_price_data
        )
        SELECT id, coin_id, symbol, name, current_price, market_cap, total_volume, price_change_percentage_24h, last_updated, ingestion_timestamp
        FROM latest_records
        WHERE rn = 1;
    END;
    $$ LANGUAGE plpgsql;
    ```

### 5. Configure Environment Variables
3.  **Get API Keys**: Go to **Project Settings** > **API**. You will need the **Project URL** and the `anon` `public` **Project API Key**.

1.  Create a file named `.env` in the root of the project directory.
2.  Add your credentials and API keys to this file. This file should **never** be committed to version control.
### 2. Local Development

1.  **Clone Repository**: `git clone <your-repository-url>`
2.  **Install Dependencies**: `pip install -r requirements.txt`
3.  **Create `.env` file**: Create a `.env` file in the root directory and add your secrets.

    ```ini
    # .env file
    # .env file for local development
    SUPABASE_URL="YOUR_SUPABASE_PROJECT_URL"
    SUPABASE_KEY="YOUR_SUPABASE_ANON_PUBLIC_KEY"

    # -- PostgreSQL Database Password --
    DB_PASSWORD="your_postgres_password"

    # -- Email Configuration (using Gmail App Password) --
    # Optional: for testing alerts
    EMAIL_SENDER_ADDRESS="your_email@gmail.com"
    EMAIL_SENDER_PASSWORD="your_16_character_app_password"
    EMAIL_RECEIVER_ADDRESS="email_to_send_alerts_to@example.com"

    # -- Telegram Configuration --
    TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
    TELEGRAM_CHAT_ID="your_telegram_chat_id"
    ```

### Using Supabase as the Database
4.  **Run the App**: `streamlit run app.py`

If you are using Supabase, you **must** use the **Connection Pooler** details for a stable deployment on platforms like Streamlit Cloud.
### 3. Deploy to Streamlit Community Cloud

1.  In your Supabase project, go to **Project Settings** (gear icon) > **Database**.
2.  Scroll down to the **Connection pooling** section.
3.  Ensure the `Transaction` mode is selected.
4.  You will see a URI. Note the **Host** and **Port** (`6543`). The host will look something like `aws-0-us-east-1.pooler.supabase.com`.
5.  Your `.env` file (for local testing) or Streamlit Secrets (for deployment) should use these values:
1.  **Push to GitHub**: Push your project (including `app.py`, `requirements.txt`, and `.gitignore`) to a public GitHub repository.
2.  **Deploy on Streamlit**:
    -   Go to share.streamlit.io and click **"New app"**.
    -   Select your repository and ensure the main file path is `app.py`.
    -   Under **"Advanced settings..."**, add your secrets in TOML format.

    ```ini
    # .env file for Supabase Connection Pooler
    # Use the HOST from the "Connection pooling" section
    DB_HOST="aws-0-us-east-1.pooler.supabase.com"
    # Use the PORT from the "Connection pooling" section
    DB_PORT="6543"
    # This is your project's database password
    DB_PASSWORD="your_supabase_project_password"
    ```toml
    # Streamlit Secrets
    SUPABASE_URL = "YOUR_SUPABASE_PROJECT_URL"
    SUPABASE_KEY = "YOUR_SUPABASE_ANON_PUBLIC_KEY"

    # Optional: for default alert contacts
    EMAIL_SENDER_ADDRESS = "your_email@gmail.com"
    EMAIL_SENDER_PASSWORD = "your_16_character_app_password"
    EMAIL_RECEIVER_ADDRESS = "email_to_send_alerts_to@example.com"
    TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"
    TELEGRAM_CHAT_ID = "your_telegram_chat_id"
    ```

## Running the Project

The project consists of two main components that should be run in separate terminals.

### Step 1: Run the Data Pipeline

The pipeline script is designed to run once and then exit. It should be executed by a scheduler (see Deployment section below). To run it manually for the first time or for testing:

```sh
python crypto_realtime_alerts_pipeline.py
```

This will set up the database tables and indexes on the first run.

### Step 2: Run the Streamlit Dashboard

In a second terminal, run the following command:

```sh
streamlit run crypto_dashboard.py
```

This will start the web server and open the interactive dashboard in your browser.

## Deployment & Scheduling

To make this a true real-time pipeline, the `crypto_realtime_alerts_pipeline.py` script needs to be run periodically. The following guide explains how to set this up on Windows using Task Scheduler to run every 10 minutes.

### Scheduling with Windows Task Scheduler

1.  **Open Task Scheduler**: Press the Windows Key and search for "Task Scheduler".
2.  **Create Task**: In the "Actions" pane on the right, click **Create Task...** (do not use "Create Basic Task").
3.  **General Tab**:
    -   **Name**: Give it a descriptive name, like `Crypto Pipeline - 10min Run`.
    -   Select **"Run whether user is logged on or not"** to ensure it runs in the background.
4.  **Triggers Tab**:
    -   Click **New...**.
    -   **Begin the task**: `On a schedule`.
    -   **Settings**: Select `Daily`.
    -   **Advanced settings**:
        -   Check **"Repeat task every"**.
        -   Set the interval to **10 minutes**.
        -   Set the duration to **Indefinitely**.
        -   Ensure **"Enabled"** is checked at the bottom.
    -   Click **OK**.
5.  **Actions Tab**:
    -   Click **New...**.
    -   **Action**: `Start a program`.
    -   **Program/script**: You need the **full path** to the `python.exe` executable inside your Conda environment. You can find this by activating your environment and running `where python`. It will look something like: `C:\Users\xxx\.conda\envs\crypto-pipeline\python.exe`.
    -   **Add arguments (optional)**: Provide the **full path** to your pipeline script. For example: `C:\Users\xxx\RealTimeCryptoPricePipelineWithAlerts\crypto_realtime_alerts_pipeline.py`.
    -   **Start in (optional)**: Provide the directory where your script is located. This helps ensure that relative paths (like for the `.env` file) work correctly. For example: `C:\Users\xxx\RealTimeCryptoPricePipelineWithAlerts\`.
    -   Click **OK**.
6.  **Save the Task**: Click **OK** to save the task. You may be prompted to enter your Windows user password.

The task is now set up and will automatically execute your pipeline script every 10 minutes.
3.  Click **"Deploy!"**.