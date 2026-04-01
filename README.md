# Cash Expense Tracker Bot

A Telegram bot that watches a family group chat for expense messages (e.g. `30 חלב`) and logs them into a Google Sheet automatically, then reacts with 👍 to confirm.

## How It Works

1. Family members send a message in the Telegram group: `<amount> <description>`
2. The bot parses the amount and description
3. It writes a row to the Google Sheet with: תאריך, תיאור, חובה, זכות, תנועה
4. It reacts with 👍 to the message so everyone knows it was recorded

---

## Setup Guide (Step by Step)

### Step 1: Create the Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. "Family Expenses Bot")
4. Choose a username (e.g. `family_expenses_12345_bot` — must end with `bot`)
5. BotFather will give you a **token** like `7123456789:AAH...` — save this!

### Step 2: Disable Group Privacy for the Bot

By default, bots can only see commands (messages starting with `/`). You must disable this so the bot can see expense messages like `30 חלב`.

1. Open **@BotFather** on Telegram
2. Send `/mybots` → select your bot
3. Go to **Bot Settings** → **Group Privacy** → tap **Turn off**
4. It should say "Privacy mode is disabled for YourBot"

### Step 3: Create a Telegram Group and Get the Chat ID

1. Create a new Telegram group (e.g. "הוצאות משפחתיות")
2. Add your bot to the group (search for its username)
3. **Important:** Go to group settings → make the bot an **admin** (it needs this to react to messages)
4. Send any message in the group (e.g. "hello")
5. Open this URL in your browser (replace `YOUR_TOKEN` with the actual token):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
6. Look for `"chat":{"id":-100xxxxxxxxxx}` — that negative number is your **Chat ID**

> **Note:** If you already added the bot to the group before disabling Group Privacy, you must **remove the bot from the group and add it back** (then make it admin again). The privacy change only takes effect for groups joined after the change.

### Step 4: Set Up Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Google Sheets API**:
   - Go to "APIs & Services" → "Library"
   - Search for "Google Sheets API" and click **Enable**
4. Create a **Service Account**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "Service Account"
   - Give it a name (e.g. "expense-bot")
   - Click "Done" (no need to grant extra roles)
5. Create a key for the service account:
   - Click on the service account you just created
   - Go to "Keys" tab → "Add Key" → "Create new key" → **JSON**
   - A `.json` file will download — place it in the `config/` folder (e.g. `config/google_credentials.json`)

### Step 5: Create and Share the Google Sheet

1. Go to [Google Sheets](https://sheets.google.com/) and create a new spreadsheet
2. Name it whatever you want (e.g. "הוצאות מזומן")
3. Copy the **Sheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_THE_SHEET_ID/edit
   ```
4. **Share the sheet** with the service account email:
   - Open your Google credentials JSON and find the `client_email` field (looks like `expense-bot@project-name.iam.gserviceaccount.com`)
   - Click "Share" on the Google Sheet and paste that email, give it **Editor** access

### Step 6: Configure the Bot

1. Copy the example config:
   ```
   copy config\config.example.json config\config.json
   ```
2. Edit `config/config.json` and fill in your values:
   ```json
   {
     "telegram": {
       "bot_token": "7123456789:AAHxxxxx...",
       "chat_id": -1001234567890
     },
     "google_sheets": {
       "credentials_file": "config/google_credentials.json",
       "sheet_id": "1aBcDeFgHiJkLmNoPqRsTuVwXyZ",
       "tab_name": "expenses"
     },
     "table_columns": {
       "A": "תאריך",
       "C": "תיאור",
       "E": "חובה",
       "F": "זכות",
       "G": "מאזן",
       "I": "תנועה",
       "J": "סיווג"
     }
   }
   ```

### Step 7: Run Locally (Test First!)

```bash
pip install -r requirements.txt
python main.py
```

Then send `30 חלב` in your Telegram group. You should see:
- A 👍 reaction on the message
- A new row in your Google Sheet

---

## Deployment Options

The bot needs to run 24/7 to listen for messages. Here are your options, from simplest to most robust:

### Option A: Railway (Recommended — Easiest)

[Railway](https://railway.app/) gives you a free tier and makes deployment trivial.

1. Push your code to GitHub (make sure `config/config.json` and `config/google_credentials.json` are in `.gitignore`!)
2. Go to [railway.app](https://railway.app/) and sign in with GitHub
3. Click "New Project" → "Deploy from GitHub Repo" → select your repo
4. Upload your `config/config.json` and `config/google_credentials.json` via Railway's volume mount feature
5. Railway will auto-deploy. Check the logs to make sure the bot started.

### Option B: Any VPS (DigitalOcean, Hetzner, etc.)

1. Get a cheap VPS (~$4-5/month)
2. SSH into it and clone your repo
3. Copy your `config/config.json` and `config/google_credentials.json` to the server
4. Run with Docker:
   ```bash
   docker build -t expense-bot .
   docker run -d --restart=always --name expense-bot \
     -v /path/to/config:/app/config \
     expense-bot
   ```

### Option C: Run on a Home Computer / Raspberry Pi

1. Install Python 3.12+
2. Clone the repo, add `config/config.json` and `config/google_credentials.json`
3. Run `python main.py` — keep it running (use `tmux` or `screen` on Linux, or set up as a Windows service)

---

## Google Sheet Output Format

The bot writes rows matching this column layout:

| A (תאריך) | B | C (תיאור) | D | E (חובה) | F (זכות) | G (מאזן) | H | I (תנועה) | J (סיווג) |
|---|---|---|---|---|---|---|---|---|---|
| 31/03/2026 | | חלב | | 30 | 0 | | | -30 | |
| 31/03/2026 | | מתנה לחבר | | 100 | 0 | | | -100 | |

The header row is created automatically the first time the bot writes to a new tab.

---

## Message Format

Messages must follow this format:
```
<number> <description in any language>
```

Examples:
- `30 חלב` ✓
- `100 מתנה לחבר` ✓
- `15.5 קפה` ✓
- `חלב 30` ✗ (number must come first)
- `bought milk` ✗ (no number)

Messages that don't match this pattern are silently ignored.
