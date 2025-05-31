# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.ext import MessageHandler, filters
import os
from dotenv import load_dotenv
import sqlite3
import datetime
import tempfile
from PIL import Image, ImageDraw, ImageFont
import telegram
import io
import math
import time
import csv
import logging

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in the environment variables.") 

# Conversation states
NAME, PHONE, ADDRESS = range(3)
SELECT_CUSTOMER, PRODUCT7_AMOUNT, PRODUCT10_AMOUNT = range(3, 6)
EDIT_ORDER = 6
CONFIRM_GENERATE_PDF = 7
PAYMENT_CONFIRMATION = 8
DELIVERY_CONFIRMATION = 9
EDIT_CUSTOMER_START, EDIT_NAME, EDIT_PHONE, EDIT_ADDRESS = range(10, 14)
DELETE_CUSTOMER = 14

# Telegram IDs for specific users
NEJMU_TELEGRAM_ID = os.getenv("NEJMU_TELEGRAM_ID")
ABDULBER_TELEGRAM_ID = os.getenv("ABDULBER_TELEGRAM_ID")
ABDULAZIZ_TELEGRAM_ID = os.getenv("ABDULAZIZ_TELEGRAM_ID")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SEBAHUDIN_TELEGRAM_ID = os.getenv("SEBAHUDIN_TELEGRAM_ID")

# Permission check functions
def has_full_permission(user_id):
    """Check if user has full admin permissions"""
    return str(user_id) in [ABDULAZIZ_TELEGRAM_ID, SEBAHUDIN_TELEGRAM_ID]

def has_view_only_permission(user_id):
    """Check if user has view-only permissions"""
    return str(user_id) == ABDULBER_TELEGRAM_ID

def has_receive_only_permission(user_id):
    """Check if user can only receive images"""
    return str(user_id) in [NEJMU_TELEGRAM_ID, TELEGRAM_CHAT_ID]

async def check_permission(update: Update, context: ContextTypes.DEFAULT_TYPE, allow_view_only=False):
    """Check user permissions and respond appropriately"""
    user_id = str(update.effective_user.id)
    
    if has_full_permission(user_id):
        return True
    if allow_view_only and has_view_only_permission(user_id):
        return True
    if has_receive_only_permission(user_id):
        await safe_reply(update, context, "⛔ ይህን ትዕዛዝ ለመጠቀም ፈቃድ የለዎትም!")
        return False
    
    await safe_reply(update, context,
        "⛔ ይቅርታ፣ ይህን ቦት ለመጠቀም ፈቃድ የለዎትም።\n"
        "ለትእዛዝ እና ተጨማሪ መረጃ፡\n@Abdulberrrr / @Sabhu15\nበስልክ ለማግኘት፡\n0982004078 /0900033423"
    )
    return False

async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None,parse_mode=None):
    """Safely reply to a message or edit a callback query message"""
    try:
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup)
        elif update.callback_query and update.callback_query.message:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in safe_reply: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup)

# Database and CSV management
def setup_database():
    try:
        logger.info("Attempting to connect to database...")
        conn = sqlite3.connect(
            'zad.db', 
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=10.0,
            check_same_thread=False
        )
        logger.info("Database connection established")
        
        conn.execute("PRAGMA encoding = 'UTF-8'")
        conn.execute("PRAGMA journal_mode=WAL")
        
        cursor = conn.cursor()
        logger.info("Creating tables if they don't exist...")
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE,
                phone TEXT NOT NULL,
                address TEXT NOT NULL COLLATE NOCASE,
                order_for_product7 INTEGER DEFAULT 0,
                order_for_product10 INTEGER DEFAULT 0,
                order_status TEXT DEFAULT 'not ordered',
                delivery_status TEXT DEFAULT 'not delivered',
                payment_status TEXT DEFAULT 'not paid',
                is_active INTEGER DEFAULT 1
            )
        ''')
        logger.info("Table creation SQL executed")
        
        conn.commit()
        logger.info("Changes committed")
        
        # Check if database is empty and restore from CSV if available
        cursor.execute('SELECT COUNT(*) FROM customers')
        if cursor.fetchone()[0] == 0:
            restore_from_csv(conn)
        
        export_to_csv(conn)
        
    except sqlite3.Error as e:
        logger.error(f"Database setup error: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()
            logger.info("Database connection closed")

async def import_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the process of importing customers via CSV."""
    user_id = update.message.from_user.id
    if not has_full_permission(user_id):
        await safe_reply(update, context, "ይህን ትዕዛዝ ለመጠቀም ፍቃድ የለዎትም።")
        return ConversationHandler.END
    
    await safe_reply(update, context, "እባክዎ ደንበኞችን ለመጨመር የCSV ፋይል ይላኩ። ፋይሉ መግቢያዎች መኖር አለባቸው፡ 'name', 'phone', 'address'።")
    return IMPORT_CSV

async def handle_csv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the uploaded CSV file and import customers into the database."""
    if not update.message.document or not update.message.document.file_name.endswith('.csv'):
        await safe_reply(update, context, "እባክዎ ትክክለኛ CSV ፋይል ይላኩ።")
        return IMPORT_CSV
    
    try:
        file = await update.message.document.get_file()
        file_path = os.path.join(tempfile.gettempdir(), update.message.document.file_name)
        
        # Download the file
        await file.download_to_drive(file_path)
        
        conn = sqlite3.connect('zad.db', check_same_thread=False)
        cursor = conn.cursor()
        
        inserted_count = 0
        with open(file_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Validate CSV headers
            required_headers = {'name', 'phone', 'address'}
            if not required_headers.issubset(reader.fieldnames):
                await safe_reply(update, context, "CSV ፋይሉ መግቢያዎች መኖር አለባቸው፡ 'name', 'phone', 'address'።")
                return ConversationHandler.END
            
            for row in reader:
                try:
                    cursor.execute('''
                        INSERT INTO customers (name, phone, address, is_active)
                        VALUES (?, ?, ?, 1)
                    ''', (row['name'], row['phone'], row['address']))
                    inserted_count += 1
                except Exception as e:
                    logger.error(f"Error inserting customer {row}: {e}")
                    continue  # Skip invalid rows
            
            conn.commit()
        
        # Clean up the temporary file
        os.remove(file_path)
        
        await safe_reply(update, context, f"ተሳክቷል! {inserted_count} ደንበኞች ተጨምረዋል።")
        # Optionally export the updated database to CSV for backup
        export_to_csv(conn)
        
    except Exception as e:
        logger.error(f"Error importing customers from CSV: {e}")
        await safe_reply(update, context, f"ስህተት ተፈጥሯል፡ {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()
    
    return ConversationHandler.END

async def cancel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the CSV import process."""
    context.user_data.clear()
    await safe_reply(update, context, "የCSV መጨመር ተሰርዟል። እንደገና ለመሞከር /importcustomers ይጠቀሙ።")
    return ConversationHandler.END


def export_to_csv(conn):
    """Export customer data (name, phone, address) to CSV"""
    backup_dir = "/data/backups"  # Uses the mounted volume
    os.makedirs(backup_dir, exist_ok=True) 
    backup_file = os.path.join(backup_dir, "customers_backup.csv")
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT name, phone, address FROM customers WHERE is_active = 1')
        customers = cursor.fetchall()
        
        with open(backup_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['name', 'phone', 'address'])
            writer.writerows(customers)
        logger.info("Customer data exported to CSV")
    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")

def restore_from_csv(conn):
    """Restore customer data from CSV if database is empty"""
    try:
        if not os.path.exists('/data/backups/customers_backup.csv'):
            logger.info("No CSV backup found for restoration")
            return
        
        cursor = conn.cursor()
        with open('/data/backups/customers_backup.csv', 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                cursor.execute('''
                    INSERT INTO customers (name, phone, address, is_active)
                    VALUES (?, ?, ?, 1)
                ''', (row['name'], row['phone'], row['address']))
        conn.commit()
        logger.info("Database restored from CSV")
    except Exception as e:
        logger.error(f"Error restoring from CSV: {e}")

async def add_customer(name, phone, address, update: Update):
    conn = None
    try:
        conn = sqlite3.connect(
            'zad.db',
            timeout=10.0,
            check_same_thread=False
        )
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO customers (name, phone, address, is_active)
            VALUES (?, ?, ?, 1)
        ''', (name, phone, address))
        conn.commit()
        export_to_csv(conn)
    except sqlite3.Error as e:
        await safe_reply(update, update.effective_context, f"Database error: {e}")
    finally:
        if conn:
            conn.close()

async def archive_customer(customer_id, update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('UPDATE customers SET is_active = 0 WHERE id = ?', (customer_id,))
        conn.commit()
        export_to_csv(conn)
        await safe_reply(update, context, "✅ ደንበኛው በተሳካ ሁኔታ ተሰርዞዋልሰርዞዋል!")
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
    finally:
        if conn:
            conn.close()

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context, allow_view_only=True):
        return
    
    await safe_reply(update, context,
        "ዛድ ዳቦና ኬክ መጋገርያና መሸጫ!\n"
        "ቦቱን ለመጠጠቀም:\n"
        "/add_customer - አዲስ ደንበኛ ለመጨመር \n"
        "/order - ትእዛዝ ለመሰብሰብ \n"
        "/edit_order - ትእዛዝ ለመስተካከል\n"
        "/generate_pdf - ሪፖርት ለመግለጫ\n"
        "/customer_list - ደንበኞችን ለማየት\n"
        "/deliver - ትእዛዝ ለማድረስ\n"
        "/payment - ክፍያ ለመቀበል\n"
        "/edit_customer - ደንበኛ መረጃ ለመስተካከል\n"
        "/delete_customer - ደንበኛ ለመሰረዝ"
    )
    return ConversationHandler.END

async def add_customer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context):
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    await safe_reply(update, context, "የደንበኛው ስም:")
    return NAME

async def add_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await safe_reply(update, context, "የደንበኛው ስልክ ቁጥር:")
    return PHONE

async def add_customer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await safe_reply(update, context, "የደንበኛው አድራሻ:")
    return ADDRESS

async def add_customer_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['address'] = update.message.text
    try:
        await add_customer(
            context.user_data['name'],
            context.user_data['phone'],
            context.user_data['address'],
            update
        )
        await safe_reply(update, context, f"{context.user_data['name']} ወደ ሲስተም ገብቶዋል.")
        await safe_reply(update, context, "✅ ደንበኛው በትክክል ተመዝግቦዋል!")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        await safe_reply(update, context, f"Error: {str(e)}")
        context.user_data.clear()
        return ConversationHandler.END

async def delete_customer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_full_permission(str(update.effective_user.id)):
        await safe_reply(update, context, "⛔ ይህን ትዕዛዝ ለመጠቀም ፈቃድ የለዎትም!")
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, phone FROM customers WHERE is_active = 1 ORDER BY name')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ንቁ ደንበኛ የለም።")
            return ConversationHandler.END
            
        keyboard = []
        half = math.ceil(len(customers)/2)
        for i in range(half):
            row = []
            customer1 = customers[i]
            row.append(InlineKeyboardButton(
                f"{customer1[1]} ({customer1[2]})", 
                callback_data=f"delete_{customer1[0]}"))
                
            if i + half < len(customers):
                customer2 = customers[i + half]
                row.append(InlineKeyboardButton(
                    f"{customer2[1]} ({customer2[2]})", 
                    callback_data=f"delete_{customer2[0]}"))
            keyboard.append(row)
            
        keyboard.append([InlineKeyboardButton("❌ መሰረዝ የለም", callback_data="cancel_delete")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context,
            "ለመሰረዝ የሚፈልጉትን ደንበኛ ይምረጡ:",
            reply_markup=reply_markup
        )
        return DELETE_CUSTOMER
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def confirm_delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_delete":
        await safe_reply(update, context, "የደንበኛ መሰረዝ ተቋርጧል።")
        context.user_data.clear()
        return ConversationHandler.END
    
    customer_id = int(query.data.split('_')[1])
    await archive_customer(customer_id, update, context)
    context.user_data.clear()
    return ConversationHandler.END

async def customer_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context, allow_view_only=True):
        return
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('SELECT name, phone FROM customers WHERE order_status = "ordered" AND is_active = 1')
        ordered_customers = cursor.fetchall()
        
        cursor.execute('SELECT name, phone FROM customers WHERE order_status = "not ordered" AND is_active = 1')
        not_ordered_customers = cursor.fetchall()
        
        response = "📋 የደንበኛ ማውጫ:\n\n"
        
        if ordered_customers:
            response += "✅ ትእዛዝ ያላቸው ደንበኞች:\n"
            for customer in ordered_customers:
                response += f"- {customer[0]} ({customer[1]})\n"
            response += "\n"
        
        if not_ordered_customers:
            response += "⏳ ትእዛዝ የሌላቸው ደንበኞች:\n"
            half = math.ceil(len(not_ordered_customers)/2)
            for i in range(half):
                customer1 = not_ordered_customers[i]
                line = f"- {customer1[0]}"
                if i + half < len(not_ordered_customers):
                    customer2 = not_ordered_customers[i + half]
                    line += f"{' '*(30-len(customer1[0]))}- {customer2[0]}"
                response += line + "\n"
        
        if not ordered_customers and not not_ordered_customers:
            response = "ምንም ንቁ ደንበኛ የለም."
            
        await safe_reply(update, context, response)
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"ችግር ተከስቶዋል: {e}")
    finally:
        if conn:
            conn.close()
    return ConversationHandler.END

async def customer_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context, allow_view_only=True):
        return
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT name, phone, address FROM customers WHERE is_active = 1 ORDER BY name')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ንቁ ደንበኛ የለም።")
            return
        
        response = "📋 የደንበኞች ዝርዝር:\n\n"
        for i, (name, phone, address) in enumerate(customers, start=1):
            response += (
                f"{i}. {name}\n"
                f"   📞 {phone}\n"
                f"   🏠 {address}\n\n"
            )
        
        for chunk in [response[i:i+4000] for i in range(0, len(response), 4000)]:
            await safe_reply(update, context, chunk, parse_mode='HTML')
            
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
    finally:
        if conn:
            conn.close()
    return ConversationHandler.END

async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context):
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name FROM customers WHERE order_status = "not ordered" AND is_active = 1')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "የሁሉንም ደንበኞች ትእዛዝ ተቀብለሃል!")
            return ConversationHandler.END
            
        keyboard = []
        half = math.ceil(len(customers)/2)
        for i in range(half):
            row = []
            customer1 = customers[i]
            row.append(InlineKeyboardButton(customer1[1], callback_data=str(customer1[0])))
            if i + half < len(customers):
                customer2 = customers[i + half]
                row.append(InlineKeyboardButton(customer2[1], callback_data=str(customer2[0])))
            keyboard.append(row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context,
            "ትእዛዝ የምትቀበለውን ደንበኛ ምረጥ:",
            reply_markup=reply_markup
        )
        return SELECT_CUSTOMER
    except sqlite3.Error as e:
        await safe_reply(update, context, f"Database error: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def select_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['customer_id'] = int(query.data)
    await safe_reply(update, context, "የባለ 7 ብዛት:")
    return PRODUCT7_AMOUNT

async def get_product7_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text)
        if amount < 0:
            raise ValueError("ብዛት ከ 0 በታች አይሆንም")
            
        context.user_data['product7'] = amount
        await safe_reply(update, context, "የባለ 10 ብዛት:")
        return PRODUCT10_AMOUNT
    except ValueError:
        await safe_reply(update, context, "እባክዎ ለ ባለ 7 ብዛት ሙሉ ቁጥር ያስገቡ፡")
        return PRODUCT7_AMOUNT

async def get_product10_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        amount = int(update.message.text)
        if amount < 0:
            raise ValueError("ብዛት ከ 0 በታች አይሆንም")
            
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE customers 
            SET 
                order_for_product7 = ?,
                order_for_product10 = ?,
                order_status = 'ordered'
            WHERE id = ?
        ''', (
            context.user_data['product7'],
            amount,
            context.user_data['customer_id']
        ))
        conn.commit()
        export_to_csv(conn)
        
        cursor.execute('SELECT COUNT(*) FROM customers WHERE order_status = "not ordered" AND is_active = 1')
        remaining = cursor.fetchone()[0]
        
        if remaining == 0:
            keyboard = [
                [InlineKeyboardButton("✅ አዎ ሪፖርት ይሰራ", callback_data="generate_pdf")],
                [InlineKeyboardButton("❌ አይደለም ይቅር", callback_data="cancel_pdf")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await safe_reply(update, context,
                "ሁሉንም ደንበኞች ትእዛዝ ተመዝግበዋል። ሪፖርት ይሰራ?",
                reply_markup=reply_markup
            )
            return CONFIRM_GENERATE_PDF
        else:
            cursor.execute('SELECT name FROM customers WHERE id = ?', (context.user_data['customer_id'],))
            customer_name = cursor.fetchone()[0]
            
            await safe_reply(update, context,
                f"✅ ትእዛዝ ለ {customer_name} ተመዝግቧል:\n"
                f"ባለ 7: {context.user_data['product7']}\n"
                f"ባለ 10: {amount}\n\n"
                f"ቀሩ {remaining} ደንበኞች ትእዛዝ አልተመዘገበላቸውም"
            )
            context.user_data.clear()
            return await order(update, context)
            
    except ValueError:
        await safe_reply(update, context, "እባክዎ ለ ባለ 10 ብዛት ሙሉ ቁጥር ያስገቡ፡")
        return PRODUCT10_AMOUNT
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def confirm_generate_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "generate_pdf":
        await safe_reply(update, context, "ሪፖርት እየተሰራ ነው...")
        await generate_order_report_pdf(update, context)
    else:
        await safe_reply(update, context, "ሪፖርት አልተፈጠረም። በማንኛውም ጊዜ /generate_pdf በመጠቀም ሪፖርት መፍጠር ይችላሉ።")
    
    context.user_data.clear()
    return ConversationHandler.END

async def generate_order_report_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context):
        return ConversationHandler.END
    
    try:
        # Font loading function
        def load_font(font_path, size):
            try:
                return ImageFont.truetype(font_path, size)
            except:
                try:
                    import requests
                    from io import BytesIO
                    url = f"https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansEthiopic/{font_path}"
                    response = requests.get(url, timeout=10)
                    font_file = BytesIO(response.content)
                    return ImageFont.truetype(font_file, size)
                except:
                    fallback_fonts = ["arial.ttf", "Arial.ttf", "FreeSans.ttf", "DejaVuSans.ttf"]
                    for font in fallback_fonts:
                        try:
                            return ImageFont.truetype(font, size)
                        except:
                            continue
                    return ImageFont.load_default(size)

        # Load fonts
        ethiopic_font = load_font("NotoSansEthiopic-Regular.ttf", 16)
        ethiopic_bold = load_font("NotoSansEthiopic-Bold.ttf", 16)
        standard_font = load_font("arial.ttf", 16)

        def get_font(text, is_header=False):
            text_str = str(text)
            if any('\u1200' <= char <= '\u137F' for char in text_str):
                return ethiopic_bold if is_header else ethiopic_font
            return standard_font

        conn = sqlite3.connect('zad.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT name, order_for_product7, order_for_product10 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
            ORDER BY name
        ''')
        
        title = "የትእዛዝ ሪፖርት"
        headers = ["የደንበኛ ስም", "7", "10", "ጠቅላላ"]
        min_widths = [220, 60, 60, 80]
        orders = cursor.fetchall()

        if not orders:
            await safe_reply(update, context, "ለሪፖርት ትእዛዞች የሉም።")
            return

        rows = []
        total_7 = total_10 = 0
        
        for order in orders:
            q7 = order[1] or 0
            q10 = order[2] or 0
            total_q = q7 + q10
            rows.append([order[0], str(q7), str(q10), str(total_q)])
            total_7 += q7
            total_10 += q10

        totals_row = ["ጠቅላላ", str(total_7), str(total_10), str(total_7 + total_10)]
        all_rows = [headers] + rows + [totals_row]
        
        # Calculate column widths
        col_widths = min_widths.copy()
        for row in all_rows:
            for i, cell in enumerate(row):
                font = get_font(cell, i == 0 or row == headers or row == totals_row)
                width = font.getlength(str(cell)) + 30
                if width > col_widths[i]:
                    col_widths[i] = width

        row_height = 40
        padding = 30
        img_width = int(sum(col_widths) + padding * 2)
        img_height = (len(all_rows) + 2) * row_height + padding * 2

        img = Image.new('RGB', (img_width, img_height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Draw title
        title_font = get_font(title, is_header=True)
        title_bbox = title_font.getbbox(title)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(
            ((img_width - title_width) / 2, padding),
            title,
            font=title_font,
            fill=(0, 0, 0)
        )

        y = padding + row_height
        for row_idx, row in enumerate(all_rows):
            x = padding
            for col_idx, cell in enumerate(row):
                is_header = row_idx in (0, len(all_rows)-1)
                font = get_font(cell, is_header)
                
                bg_color = (
                    (70, 130, 180) if row_idx == 0 else
                    (220, 220, 220) if row_idx == len(all_rows)-1 else
                    (255, 255, 255)
                )

                draw.rectangle(
                    [x, y, x + col_widths[col_idx], y + row_height],
                    fill=bg_color,
                    outline=(0, 0, 0)
                )

                text_bbox = font.getbbox(str(cell))
                text_height = text_bbox[3] - text_bbox[1]
                text_y = y + (row_height - text_height) // 2

                text_color = (0, 0, 0)
                if row_idx == 0:
                    text_color = (255, 255, 255)

                text_x = x + 15
                if col_idx > 0:
                    cell_width = col_widths[col_idx]
                    text_width = font.getlength(str(cell))
                    text_x = x + (cell_width - text_width) // 2

                draw.text(
                    (text_x, text_y),
                    str(cell),
                    font=font,
                    fill=text_color
                )
                x += col_widths[col_idx]
            y += row_height

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', quality=95)
        img_byte_arr.seek(0)
        
        recipients = [int(TELEGRAM_CHAT_ID)] if TELEGRAM_CHAT_ID else []
        caption = "የትእዛዝ ሪፖርት"

        for chat_id in recipients:
            try:
                img_byte_arr.seek(0)
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img_byte_arr,
                    caption=caption
                )
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")

        img_byte_arr.seek(0)
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=img_byte_arr,
            caption=caption
        )

    except Exception as e:
        error_msg = f"ስህተት ተፈጥሯል፡ {str(e)}"
        logger.error(error_msg)
        await safe_reply(update, context, error_msg)
    finally:
        if 'conn' in locals():
            conn.close()
    return ConversationHandler.END

async def edit_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context):
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, order_for_product7, order_for_product10 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
        ''')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ትእዛዝ የለም፡ እባክዎ /order ይጠቀሙ፡")
            return ConversationHandler.END
            
        keyboard = []
        half = math.ceil(len(customers)/2)
        for i in range(half):
            row = []
            customer1 = customers[i]
            row.append(InlineKeyboardButton(
                f"{customer1[1]} (7:{customer1[2]},10:{customer1[3]})", 
                callback_data=str(customer1[0])))
            if i + half < len(customers):
                customer2 = customers[i + half]
                row.append(InlineKeyboardButton(
                    f"{customer2[1]} (7:{customer2[2]},10:{customer2[3]})", 
                    callback_data=str(customer2[0])))
            keyboard.append(row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context,
            "የሚስተካከለውን ትእዛዝ ምረጥ:",
            reply_markup=reply_markup
        )
        return EDIT_ORDER
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def select_order_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['edit_customer_id'] = int(query.data)
    await safe_reply(update, context, "የባለ 7 ብዛት (ወይም /skip ለመቀጠል):")
    return PRODUCT7_AMOUNT

async def skip_product7(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['skip_product7'] = True
    await safe_reply(update, context, "የባለ 10 ብዛት እባክዎን ያስገቡ፡")
    return PRODUCT10_AMOUNT

async def skip_product10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['skip_product10'] = True
    return await finalize_order_edit(update, context)

async def finalize_order_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT order_for_product7, order_for_product10, name 
            FROM customers 
            WHERE id = ?
        ''', (context.user_data['edit_customer_id'],))
        current_7, current_10, name = cursor.fetchone()
        
        product7 = current_7 if 'skip_product7' in context.user_data else context.user_data['product7']
        product10 = current_10 if 'skip_product10' in context.user_data else int(update.message.text)
        
        cursor.execute('''
            UPDATE customers 
            SET 
                order_for_product7 = ?,
                order_for_product10 = ?
            WHERE id = ?
        ''', (product7, product10, context.user_data['edit_customer_id']))
        conn.commit()
        export_to_csv(conn)
        
        await safe_reply(update, context,
            f"✅ የተስተካከለ ትእዛዝ {name}:\n"
            f"ባለ 7: {product7}\n"
            f"ባለ 10: {product10}"
        )
        
        context.user_data.clear()
        return ConversationHandler.END
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def edit_customer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_full_permission(str(update.effective_user.id)):
        await safe_reply(update, context, "⛔ ይህን ትዕዛዝ ለመጠቀም ፈቃድ የለዎትም!")
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, phone FROM customers WHERE is_active = 1 ORDER BY name')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ንቁ ደንበኛ የለም።")
            return ConversationHandler.END
            
        keyboard = []
        half = math.ceil(len(customers)/2)
        for i in range(half):
            row = []
            customer1 = customers[i]
            row.append(InlineKeyboardButton(
                f"{customer1[1]} ({customer1[2]})", 
                callback_data=f"edit_{customer1[0]}"))
                
            if i + half < len(customers):
                customer2 = customers[i + half]
                row.append(InlineKeyboardButton(
                    f"{customer2[1]} ({customer2[2]})", 
                    callback_data=f"edit_{customer2[0]}"))
            keyboard.append(row)
            
        keyboard.append([InlineKeyboardButton("❌ የሚስተካከል የለም", callback_data="cancel_edit")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_reply(update, context,
            "የትንሽ መረጃ ለመስተካከል የሚፈልጉትን ደንበኛ ይምረጡ:",
            reply_markup=reply_markup
        )
        return EDIT_CUSTOMER_START
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def select_customer_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_edit":
        await safe_reply(update, context, "የደንበኛ መረጃ ማስተካከያ ተቋርጧል።")
        context.user_data.clear()
        return ConversationHandler.END
    
    customer_id = int(query.data.split('_')[1])
    context.user_data['edit_customer_id'] = customer_id
    
    keyboard = [
        [InlineKeyboardButton("ስም", callback_data="edit_name")],
        [InlineKeyboardButton("ስልክ", callback_data="edit_phone")],
        [InlineKeyboardButton("አድራሻ", callback_data="edit_address")],
        [InlineKeyboardButton("❌ ስራውን አቁም", callback_data="cancel_edit")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_reply(update, context,
        "የደንበኛውን ምን ዓይነት መረጃ ማስተካከል ይፈልጋሉ?",
        reply_markup=reply_markup
    )
    return EDIT_CUSTOMER_START

async def ask_for_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_reply(update, context, "እባክዎ የደንበኛውን አዲስ ስም ያስገቡ:")
    return EDIT_NAME

async def ask_for_new_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_reply(update, context, "እባክዎ የደንበኛውን አዲስ ስልክ ቁጥር ያስገቡ:")
    return EDIT_PHONE

async def ask_for_new_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_reply(update, context, "እባክዎ የደንበኛውን አዲስ አድራሻ ያስገቡ:")
    return EDIT_ADDRESS

async def save_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text
    customer_id = context.user_data['edit_customer_id']
    
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE customers 
            SET name = ? 
            WHERE id = ?
        ''', (new_name, customer_id))
        conn.commit()
        export_to_csv(conn)
        
        await safe_reply(update, context, f"✅ የደንበኛው ስም በትክክል ተስተካክሏል!")
        context.user_data.clear()
        return await edit_customer_start(update, context)
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def save_new_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_phone = update.message.text
    customer_id = context.user_data['edit_customer_id']
    
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE customers 
            SET phone = ? 
            WHERE id = ?
        ''', (new_phone, customer_id))
        conn.commit()
        export_to_csv(conn)
        
        await safe_reply(update, context, f"✅ የደንበኛው ስልክ ቁጥር በትክክል ተስተካክሏል!")
        context.user_data.clear()
        return await edit_customer_start(update, context)
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def save_new_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_address = update.message.text
    customer_id = context.user_data['edit_customer_id']
    
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE customers 
            SET address = ? 
            WHERE id = ?
        ''', (new_address, customer_id))
        conn.commit()
        export_to_csv(conn)
        
        await safe_reply(update, context, f"✅ የደንበኛው አድራሻ በትክክል ተስተካክሏል!")
        context.user_data.clear()
        return await edit_customer_start(update, context)
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        context.user_data.clear()
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context, allow_view_only=True):
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, order_for_product7, order_for_product10, payment_status 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
            ORDER BY name
        ''')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ትእዛዝ የለም። በመጀመሪያ ትእዛዝ ይጨምሩ።")
            return ConversationHandler.END
            
        context.user_data['payment_customers'] = customers
        context.user_data['payment_viewers'] = {}  # Track viewers' chat_id and message_id
        
        message_id = await send_payment_buttons(update, context, customers)
        
        if message_id is not None:
            context.user_data['payment_message_id'] = message_id
            if has_view_only_permission(str(update.effective_user.id)):
                context.user_data['payment_viewers'][update.effective_chat.id] = message_id
        
        return PAYMENT_CONFIRMATION
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

async def send_payment_buttons(update, context, customers):
    keyboard = []
    for customer in customers:
        q7 = customer[2] or 0
        q10 = customer[3] or 0
        total = (q7 * 7) + (q10 * 10)
        payment_status = "✅" if customer[4] == 'paid' else "💵"
        
        button_text = f"{customer[1]}: {total}ብር {payment_status}"
        
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pay_{customer[0]}")])
        else:
            keyboard.append([InlineKeyboardButton(button_text, callback_data="view_only")])
    
    all_paid = all(c[4] == 'paid' for c in customers)
    if all_paid:
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton("✅ ሁሉንም ክፍያዎች ተቀብያለሁ", callback_data="finish_payment")])
        else:
            keyboard.append([InlineKeyboardButton("✅ ሁሉንም ክፍያዎች ተከናውኗል (ይዩት)", callback_data="view_only")])
    else:
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton("🔚 ክፍያዎችን ጨርሰዋል", callback_data="finish_payment")])
        else:
            keyboard.append([InlineKeyboardButton("🔚 ክፍያዎችን ይዩት", callback_data="view_only")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if 'payment_message_id' in context.user_data:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['payment_message_id'],
                text="ክፍያዎችን ለመቀበል የደንበኛውን ስም ይጫኑ:\n"
                     "✅ - ክፍያ ተከናውኗል\n"
                     "💵 - ክፍያ ያልተከናወነ",
                reply_markup=reply_markup
            )
            return None
        except Exception as e:
            logger.error(f"Failed to edit payment message: {e}")
    
    message = await safe_reply(update, context,
        "ክፍያዎችን ለመቀበል የደንበኛውን ስም ይጫኑ:\n"
        "✅ - ክፍያ ተከናውኗል\n"
        "💵 - ክፍያ ያልተከናወነ",
        reply_markup=reply_markup
    )
    return message.message_id if hasattr(message, 'message_id') else None
async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    
    if query.data == "view_only":
        await query.answer("ይቅርታ፣ ይህን ለመቀየር ፈቃድ የለዎትም!", show_alert=True)
        return PAYMENT_CONFIRMATION
    
    if query.data == "finish_payment":
        conn = None
        try:
            conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM customers WHERE order_status = "ordered" AND payment_status != "paid" AND is_active = 1')
            unpaid_count = cursor.fetchone()[0]
            
            if unpaid_count == 0:
                if has_full_permission(user_id):
                    keyboard = [
                        [InlineKeyboardButton("✅ አዎ ሪፖርት ይፍጠሩ", callback_data="generate_payment_pdf")],
                        [InlineKeyboardButton("❌ አይደለም ይቅር", callback_data="cancel_payment")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        await safe_reply(update, context,
                            "ሁሉንም ክፍያዎች ተቀብለዋል። የክፍያ ሪፖርት ይፈጥሩ?",
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error sending payment report prompt: {e}")
                        await safe_reply(update, context, f"ስህተት ተፈጥሯል፡ {str(e)}")
                else:
                    await safe_reply(update, context, "ሁሉንም ክፍያዎች ተቀብለዋል!")
                context.user_data.clear()
            else:
                await safe_reply(update, context,
                    f"አሁንም {unpaid_count} ክፍያዎች ይቀራሉ። ክፍያዎችን ለመቀጠል /payment ይጠቀሙ።"
                )
                context.user_data.clear()
                return ConversationHandler.END
        finally:
            if conn:
                conn.close()
    
    # Handle individual payment status toggle
    if not has_full_permission(user_id):
        await query.answer("ይቅርታ፣ ይህን ለመቀየር ፈቃድ የለዎትም!", show_alert=True)
        return PAYMENT_CONFIRMATION
    try:
        if query.data.startswith('pay_'):
            customer_id = int(query.data.split('_')[1])
        else:
            customer_id = None
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data: {query.data}")
    
    
    conn = None
    if customer_id:
        try:
            conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute('SELECT payment_status FROM customers WHERE id = ?', (customer_id,))
            current_status = cursor.fetchone()[0]
            
            new_status = 'paid' if current_status != 'paid' else 'not paid'
            cursor.execute('UPDATE customers SET payment_status = ? WHERE id = ?', (new_status, customer_id))
            conn.commit()
            export_to_csv(conn)
            
            cursor.execute('''
                SELECT id, name, order_for_product7, order_for_product10, payment_status 
                FROM customers 
                WHERE order_status = "ordered" AND is_active = 1
                ORDER BY name
            ''')
            customers = cursor.fetchall()
            context.user_data['payment_customers'] = customers
            
            await send_payment_buttons(update, context, customers)
            
            # Update all view-only users' payment messages
            for chat_id, message_id in context.user_data.get('payment_viewers', {}).items():
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="ክፍያዎችን ለመቀበል የደንበኛውን ስም ይጫኑ:\n"
                            "✅ - ክፍያ ተከናውኗል\n"
                            "💵 - ክፍያ ያልተከናወነ",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"{c[1]}: {(c[2] or 0)*7 + (c[3] or 0)*10}ብር {'✅' if c[4] == 'paid' else '💵'}",
                                callback_data="view_only"
                            )] for c in customers
                        ] + [[InlineKeyboardButton("🔚 ክፍያዎችን ይዩት", callback_data="view_only")]])
                    )
                except Exception as e:
                    logger.error(f"Failed to update payment message for chat {chat_id}: {e}")
            
            return PAYMENT_CONFIRMATION
        finally:
            if conn:
                conn.close()
async def generate_payment_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"generate_payment_pdf called with callback_data: {query.data}")
    
    try:
        if query.data == "generate_payment_pdf":
            await safe_reply(update, context, "የክፍያ ሪፖርት እየተፈጠረ ነው...")
            logger.info("Attempting to generate payment report")
            await generate_payment_report(update, context)
            logger.info("Payment report generated successfully")
        else:
            await safe_reply(update, context, "የክፍያ ሪፖርት አልተፈጠረም። በማንኛውም ጊዜ /payment በመጠቀም እንደገና ማድረግ ይችላሉ።")
    except Exception as e:
        logger.error(f"Error generating payment report: {e}")
        await safe_reply(update, context, f"ስህተት ተፈጥሯል፡ {str(e)}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def generate_payment_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context):
        return ConversationHandler.END
    
    try:
        # Font loading function (same as before)
        def load_font(font_path, size):
            try:
                return ImageFont.truetype(font_path, size)
            except:
                try:
                    import requests
                    from io import BytesIO
                    url = f"https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansEthiopic/{font_path}"
                    response = requests.get(url, timeout=10)
                    font_file = BytesIO(response.content)
                    return ImageFont.truetype(font_file, size)
                except:
                    fallback_fonts = ["arial.ttf", "Arial.ttf", "FreeSans.ttf", "DejaVuSans.ttf"]
                    for font in fallback_fonts:
                        try:
                            return ImageFont.truetype(font, size)
                        except:
                            continue
                    return ImageFont.load_default(size)

        # Load fonts
        ethiopic_font = load_font("NotoSansEthiopic-Regular.ttf", 16)
        ethiopic_bold = load_font("NotoSansEthiopic-Bold.ttf", 16)
        standard_font = load_font("arial.ttf", 16)

        def get_font(text, is_header=False):
            text_str = str(text)
            if any('\u1200' <= char <= '\u137F' for char in text_str):
                return ethiopic_bold if is_header else ethiopic_font
            return standard_font

        conn = sqlite3.connect('zad.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT name, order_for_product7, order_for_product10, payment_status 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
            ORDER BY name
        ''')
        
        title = "የክፍያ ሪፖርት"
        headers = ["የደንበኛ ስም", "7", "10", "ጠቅላላ", "ክፍያ", "ጠቅላላ"]
        min_widths = [220, 60, 60, 80, 100, 80]  # Adjusted widths for new text
        orders = cursor.fetchall()

        if not orders:
            await safe_reply(update, context, "ለሪፖርት ትእዛዞች የሉም።")
            return

        rows = []
        total_7 = total_10 = total_money = 0
        
        for order in orders:
            q7 = order[1] or 0
            q10 = order[2] or 0
            total_q = q7 + q10
            money = (q7 * 7) + (q10 * 10)
            
            # Use clear text instead of symbols
            payment_status = "Paid" if order[3] == 'paid' else "Not Paid"
            
            rows.append([
                order[0], 
                str(q7), 
                str(q10), 
                str(total_q),
                payment_status,
                str(money)  # Remove "ብር"
            ])
            
            total_7 += q7
            total_10 += q10
            total_money += money

        totals_row = [
            "ጠቅላላ", 
            str(total_7), 
            str(total_10), 
            str(total_7 + total_10),
            "",
            str(total_money)  # Remove "ብር"
        ]

        all_rows = [headers] + rows + [totals_row]
        
        # Calculate column widths
        col_widths = min_widths.copy()
        for row in all_rows:
            for i, cell in enumerate(row):
                font = get_font(cell, i == 0 or row == headers or row == totals_row)
                width = font.getlength(str(cell)) + 30
                if width > col_widths[i]:
                    col_widths[i] = width

        row_height = 40
        padding = 30
        img_width = int(sum(col_widths) + padding * 2)
        img_height = (len(all_rows) + 2) * row_height + padding * 2

        img = Image.new('RGB', (img_width, img_height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Draw title
        title_font = get_font(title, is_header=True)
        title_bbox = title_font.getbbox(title)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(
            ((img_width - title_width) / 2, padding),
            title,
            font=title_font,
            fill=(0, 0, 0)
        )

        y = padding + row_height
        for row_idx, row in enumerate(all_rows):
            x = padding
            for col_idx, cell in enumerate(row):
                is_header = row_idx in (0, len(all_rows)-1)
                font = get_font(cell, is_header)
                
                bg_color = (
                    (70, 130, 180) if row_idx == 0 else
                    (220, 220, 220) if row_idx == len(all_rows)-1 else
                    (255, 255, 255)
                )

                draw.rectangle(
                    [x, y, x + col_widths[col_idx], y + row_height],
                    fill=bg_color,
                    outline=(0, 0, 0)
                )

                text_bbox = font.getbbox(str(cell))
                text_height = text_bbox[3] - text_bbox[1]
                text_y = y + (row_height - text_height) // 2

                text_color = (0, 0, 0)
                if row_idx == 0:
                    text_color = (255, 255, 255)
                elif col_idx == 4:  # Payment status column
                    text_color = (0, 128, 0) if cell == "Paid" else (255, 0, 0)

                text_x = x + 15
                if col_idx > 0:
                    cell_width = col_widths[col_idx]
                    text_width = font.getlength(str(cell))
                    text_x = x + (cell_width - text_width) // 2

                draw.text(
                    (text_x, text_y),
                    str(cell),
                    font=font,
                    fill=text_color
                )
                x += col_widths[col_idx]
            y += row_height

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', quality=95)
        img_byte_arr.seek(0)
        
        recipients = [int(TELEGRAM_CHAT_ID)] if TELEGRAM_CHAT_ID else []
        caption = f"የዛሬ ሂሳብ ሁሉም ተሰብስቦዋል \n\n" \
                    f"ቀን:- {get_current_day_amharic()}\n\n" \
                  f"አጠቃላይ ክፍያ: {total_money} ብር\n\n" \
                  

        # Send to all recipients
        for chat_id in recipients:
            try:
                img_byte_arr.seek(0)
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img_byte_arr,
                    caption=caption
                )
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")

        await safe_reply(update, context, "የክፍያ ሪፖርት በተሳካ ሁኔታ ተልኮዋል።")

        if has_full_permission(str(update.effective_user.id)):
            keyboard = [
                [InlineKeyboardButton("✅ አዎ የትናንትን መረጃ አጥፋ", callback_data="reset_data")],
                [InlineKeyboardButton("❌ አይደለም", callback_data="cancel_reset")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ሁሉንም ክፍያዎች ተቀብለናል። የትናንትን መረጃ እንዲያጠፋ ይፈልጋሉ?",
                reply_markup=reply_markup
            )

    except Exception as e:
        error_msg = f"ስህተት ተፈጥሯል፡ {str(e)}"
        logger.error(error_msg)
        await safe_reply(update, context, error_msg)
    finally:
        if 'conn' in locals():
            conn.close()
    return ConversationHandler.END

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_permission(update, context, allow_view_only=True):
        return ConversationHandler.END
    
    context.user_data.clear()  # Clear context to allow handler switching
    conn = None
    try:
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, order_for_product7, order_for_product10, delivery_status 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
            ORDER BY name
        ''')
        customers = cursor.fetchall()
        
        if not customers:
            await safe_reply(update, context, "ምንም ትእዛዝ የለም። በመጀመሪያ ትእዛዝ ይጨምሩ።")
            return ConversationHandler.END
            
        context.user_data['delivery_customers'] = customers
        context.user_data['delivery_viewers'] = {}  # Track viewers' chat_id and message_id
        
        message_id = await send_delivery_buttons(update, context, customers)
        
        if message_id is not None:
            context.user_data['delivery_message_id'] = message_id
            if has_view_only_permission(str(update.effective_user.id)):
                context.user_data['delivery_viewers'][update.effective_chat.id] = message_id
        
        return DELIVERY_CONFIRMATION
        
    except sqlite3.Error as e:
        await safe_reply(update, context, f"የዳታቤዝ ችግር: {e}")
        return ConversationHandler.END
    finally:
        if conn:
            conn.close()

def get_current_day_amharic():
    """Returns the current day in Amharic format (e.g., 'ሰኞ ሜይ 31')"""
    # English to Amharic mappings
    amharic_days = {
        'Monday': 'ሰኞ',
        'Tuesday': 'ማክሰኞ',
        'Wednesday': 'ረቡዕ',
        'Thursday': 'ሐሙስ',
        'Friday': 'ዓርብ',
        'Saturday': 'ቅዳሜ',
        'Sunday': 'እሁድ'
    }
    
    amharic_months = {
        'January': 'ጃንዩወሪ',
        'February': 'ፌብሩወሪ',
        'March': 'ማርች',
        'April': 'ኤፕሪል',
        'May': 'ሜይ',
        'June': 'ጁን',
        'July': 'ጁላይ',
        'August': 'ኦገስት',
        'September': 'ሴፕቴምበር',
        'October': 'ኦክቶበር',
        'November': 'ኖቬምበር',
        'December': 'ዲሴምበር'
    }

    now = datetime.datetime.now()
    day_en = now.strftime('%A')
    month_en = now.strftime('%B')
    day_num = now.strftime('%d')
    
    return f"{amharic_days.get(day_en, day_en)} {amharic_months.get(month_en, month_en)} {day_num} ({datetime.datetime.now().strftime('%A %B %d')})"

# Example usage:
print(get_current_day_amharic())  # Output: "ሰኞ ሜይ 31"

async def send_delivery_buttons(update, context, customers):
    not_delivered = [c for c in customers if c[4] != 'delivered']
    
    keyboard = []
    for customer in not_delivered:
        q7 = customer[2] or 0
        q10 = customer[3] or 0
        
        button_text = f"{customer[1]} (7×{q7} + 10×{q10})"
        
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"deliver_{customer[0]}")])
        else:
            keyboard.append([InlineKeyboardButton(button_text, callback_data="view_only")])
    
    all_delivered = all(c[4] == 'delivered' for c in customers)
    if all_delivered:
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton("✅ ሁሉንም ትእዛዞች አድርሰዋል", callback_data="finish_delivery")])
        else:
            keyboard.append([InlineKeyboardButton("✅ ሁሉንም ትእዛዞች ተደርሰዋል (ይዩት)", callback_data="view_only")])
    else:
        remaining = len(customers) - len(not_delivered)
        if has_full_permission(str(update.effective_user.id)):
            keyboard.append([InlineKeyboardButton(f"🔚 ጨርሰዋል ({remaining} ተደርሷል)", callback_data="finish_delivery")])
        else:
            keyboard.append([InlineKeyboardButton(f"🔚 ይዩት ({remaining} ተደርሷል)", callback_data="view_only")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if 'delivery_message_id' in context.user_data:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['delivery_message_id'],
                text="ለደንበኛ ያልደረሱ ትእዛዞች:",
                reply_markup=reply_markup
            )
            return None
        except Exception as e:
            logger.error(f"Failed to edit delivery message: {e}")
    
    message = await safe_reply(update, context,
        "ለደንበኛ ያልደረሱ ትእዛዞች:",
        reply_markup=reply_markup
    )
    return message.message_id if hasattr(message, 'message_id') else None

async def handle_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(update.effective_user.id)
    
    if query.data == "view_only":
        await query.answer("ይቅርታ፣ ይህን ለመቀየር ፈቃድ የለዎትም!", show_alert=True)
        return DELIVERY_CONFIRMATION
    
    if query.data == "finish_delivery":
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM customers WHERE order_status = "ordered" AND delivery_status != "delivered" AND is_active = 1')
        undelivered_count = cursor.fetchone()[0]
        
        if undelivered_count == 0:
            await safe_reply(update, context, "✅ ሁሉንም ትእዛዞች አድርሰዋል! በጣም ጥሩ!")
            context.user_data.clear()
            return ConversationHandler.END
        else:
            delivered_count = len(context.user_data['delivery_customers']) - undelivered_count
            await safe_reply(update, context,
                f"አሁንም {undelivered_count} ትእዛዞች ይቀራሉ። {delivered_count} ተደርሰዋል። ለመቀጠል /deliver ይጠቀሙ።"
            )
            context.user_data.clear()
            return ConversationHandler.END
    else:
        if not has_full_permission(user_id):
            await query.answer("ይቅርታ፣ ይህን ለመቀየር ፈቃድ የለዎትም!", show_alert=True)
            return DELIVERY_CONFIRMATION
        
        customer_id = int(query.data.split('_')[1])
        
        conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE customers SET delivery_status = "delivered" WHERE id = ?', (customer_id,))
        conn.commit()
        export_to_csv(conn)
        
        cursor.execute('''
            SELECT id, name, order_for_product7, order_for_product10, delivery_status 
            FROM customers 
            WHERE order_status = 'ordered' AND is_active = 1
            ORDER BY name
        ''')
        customers = cursor.fetchall()
        context.user_data['delivery_customers'] = customers
        
        await send_delivery_buttons(update, context, customers)
        
        # Update all view-only users' delivery messages
        for chat_id, message_id in context.user_data.get('delivery_viewers', {}).items():
            try:
                not_delivered = [c for c in customers if c[4] != 'delivered']
                keyboard = [
                    [InlineKeyboardButton(
                        f"(7×{c[2] or 0} + 10×{c[3] or 0})",
                        callback_data="view_only"
                    )] for c in not_delivered
                ]
                all_delivered = all(c[4] == 'delivered' for c in customers)
                if all_delivered:
                    keyboard.append([InlineKeyboardButton("✅ ሁሉንም ትእዛዞች ተደርሰዋል (ይዩት)", callback_data="view_only")])
                else:
                    remaining = len(customers) - len(not_delivered)
                    keyboard.append([InlineKeyboardButton(f"🔚 ይዩት ({remaining} ተደርሷል)", callback_data="view_only")])
                
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="ለደንበኛ ያልደረሱ ትእዛዞች:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Failed to update delivery message for chat {chat_id}: {e}")
        
        return DELIVERY_CONFIRMATION

async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "reset_data":
        if not has_full_permission(str(update.effective_user.id)):
            await safe_reply(update, context, "⛔ ይህን ትዕዛዝ ለመጠቀም ፈቃድ የለዎትም!")
            return ConversationHandler.END
            
        conn = None
        try:
            conn = sqlite3.connect('zad.db', timeout=10.0, check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE customers 
                SET 
                    order_for_product7 = 0,
                    order_for_product10 = 0,
                    order_status = 'not ordered',
                    delivery_status = 'not delivered',
                    payment_status = 'not paid'
                WHERE is_active = 1
            ''')
            conn.commit()
            export_to_csv(conn)
            
            await safe_reply(update, context, "✅ የትናንት መረጃ በተሳካ ሁኔታ ተጠፍቷል!")
        except sqlite3.Error as e:
            await safe_reply(update, context, f"የዳታቤዝ ስህተት: {e}")
        finally:
            if conn:
                conn.close()
    else:
        await safe_reply(update, context, "የመረጃ መጥፋት ተቋርጧል።")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await safe_reply(update, context, "ስራው ተቋርጧል። አዲስ ትዕዛዝ ለመጀመር እባክዎ /start ይጠቀሙ።")
    return ConversationHandler.END
IMPORT_CSV=99
def main():
    try:
        setup_database()
        
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        import_conv = ConversationHandler(
        entry_points=[CommandHandler("importcustomers", import_customers)],
        states={
            IMPORT_CSV: [
                MessageHandler(filters.Document.ALL, handle_csv_import),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_import)],
    )
        application.add_handler(import_conv)
        
        add_customer_conv = ConversationHandler(
            entry_points=[CommandHandler('add_customer', add_customer_start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_customer_name)],
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_customer_phone)],
                ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_customer_address)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        order_conv = ConversationHandler(
            entry_points=[CommandHandler('order', order)],
            states={
                SELECT_CUSTOMER: [CallbackQueryHandler(select_customer)],
                PRODUCT7_AMOUNT: [
                    MessageHandler(filters.Regex(r'^\d+$'), get_product7_amount),
                    CommandHandler('skip', skip_product7)
                ],
                PRODUCT10_AMOUNT: [
                    MessageHandler(filters.Regex(r'^\d+$'), get_product10_amount),
                    CommandHandler('skip', skip_product10)
                ],
                CONFIRM_GENERATE_PDF: [CallbackQueryHandler(confirm_generate_pdf)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        edit_order_conv = ConversationHandler(
            entry_points=[CommandHandler('edit_order', edit_order)],
            states={
                EDIT_ORDER: [CallbackQueryHandler(select_order_to_edit)],
                PRODUCT7_AMOUNT: [
                    MessageHandler(filters.Regex(r'^\d+$'), get_product7_amount),
                    CommandHandler('skip', skip_product7)
                ],
                PRODUCT10_AMOUNT: [
                    MessageHandler(filters.Regex(r'^\d+$'), finalize_order_edit),
                    CommandHandler('skip', skip_product10)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        edit_customer_conv = ConversationHandler(
            entry_points=[CommandHandler('edit_customer', edit_customer_start)],
            states={
                EDIT_CUSTOMER_START: [
                    CallbackQueryHandler(ask_for_new_name, pattern='^edit_name$'),
                    CallbackQueryHandler(ask_for_new_phone, pattern='^edit_phone$'),
                    CallbackQueryHandler(ask_for_new_address, pattern='^edit_address$'),
                    CallbackQueryHandler(select_customer_to_edit)
                ],
                EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_name)],
                EDIT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_phone)],
                EDIT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_address)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        payment_conv = ConversationHandler(
            entry_points=[CommandHandler('payment', payment)],
            states={
                PAYMENT_CONFIRMATION: [
                    CallbackQueryHandler(handle_payment, pattern=r'^(pay_\d+|view_only|finish_payment)$'),
                    CallbackQueryHandler(generate_payment_pdf, pattern='^(generate_payment_pdf|cancel_payment)$')
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        delivery_conv = ConversationHandler(
            entry_points=[CommandHandler('deliver', deliver)],
            states={
                DELIVERY_CONFIRMATION: [CallbackQueryHandler(handle_delivery)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        delete_customer_conv = ConversationHandler(
            entry_points=[CommandHandler('delete_customer', delete_customer_start)],
            states={
                DELETE_CUSTOMER: [CallbackQueryHandler(confirm_delete_customer)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('customer_list', customer_list))
        application.add_handler(CommandHandler('customer_info', customer_info))
        application.add_handler(CommandHandler('generate_pdf', generate_order_report_pdf))

        application.add_handler(CallbackQueryHandler(reset_data, pattern='^(reset_data|cancel_reset)$'))
        application.add_handler(add_customer_conv)
        application.add_handler(order_conv)
        application.add_handler(edit_order_conv)
        application.add_handler(edit_customer_conv)
        application.add_handler(payment_conv)
        application.add_handler(delivery_conv)
        application.add_handler(delete_customer_conv)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except telegram.error.NetworkError as e:
        logger.error(f"Network error: {e}")
        time.sleep(10)
        main()   
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        time.sleep(10)
        main()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.") 
