# ZAD Try

ZAD Try is an expanded version of the ZAD bakery Telegram bot with stronger data handling, CSV backup support, safer reply helpers, and extra customer management commands.

## Main Concept

The project manages a bakery ordering workflow from Telegram. It keeps customer records in SQLite, lets authorized users collect daily product quantities, tracks payment and delivery completion, exports customer backups to CSV, and supports restoring data when deployed with persistent storage.

## Key Features

- Add, edit, archive, and list customers
- Import customers from CSV
- Export active customer data to CSV backup
- Record product orders
- Track payment and delivery status
- Generate reports
- Reset active daily order fields after completion
- Role-based access using Telegram IDs

## Tech Stack

- Python
- `python-telegram-bot`
- SQLite
- CSV backup files
- Pillow for report rendering
- `python-dotenv`

## Setup

```bash
pip install -r requirements.txt
python main.py
```

Required secrets should be stored in `.env`, especially the Telegram bot token and allowed Telegram user IDs.
