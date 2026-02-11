import asyncio
import math
import time
import json
import hashlib
import logging
import httpx
import random
from typing import Optional
import requests
from telegram import ReplyKeyboardMarkup, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ExtBot, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)
import unicodedata
from datetime import datetime, timedelta

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = "8547410438:AAGWjGgsl9evtZ3_Iqsf0vBlLplybcUtoTY"
BASE_URL = "https://api.bigwinqaz.com/api/webapi/"
IGNORE_SSL = True
WIN_LOSE_CHECK_INTERVAL = 2
MAX_RESULT_WAIT_TIME = 60
ADMIN_ID = 5858273413 
MAX_BALANCE_RETRIES = 10
BALANCE_RETRY_DELAY = 5
BALANCE_API_TIMEOUT = 20
BET_API_TIMEOUT = 30
MAX_BET_RETRIES = 3
BET_RETRY_DELAY = 5
MAX_CONSECUTIVE_ERRORS = 5
MESSAGE_RATE_LIMIT_SECONDS = 10
MAX_TELEGRAM_RETRIES = 3
TELEGRAM_RETRY_DELAY = 2
WINGO_GAME_TYPE = 30
WINGO_LANGUAGE = 7
DEFAULT_BS_ORDER = "BSBBSBSSSB"
VIRTUAL_BALANCE = 786700

user_state = {}
user_temp = {}
user_sessions = {}
user_settings = {}
user_pending_bets = {}
user_waiting_for_result = {}
user_stats = {}
user_game_info = {}
allowed_777bigwin_ids = set()
user_sessions = {}
user_skipped_bets = {}
user_should_skip_next = {}
user_balance_warnings = {}
user_skip_result_wait = {}
user_stop_initiated = {}
user_command_locks = {}
user_last_numbers = {}
user_all_results = {}
user_result_history = {}
user_last_10_results = {}
user_lyzo_round_count = {}
user_ai_last_10_results = {}
user_ai_round_count = {}
user_sl_skip_waiting_for_win = {}

def load_allowed_users():
    global allowed_777bigwin_ids
    try:
        with open('users_777bigwin.json', 'r') as f:
            data = json.load(f)
            allowed_777bigwin_ids = set(data.get('allowed_ids', []))
            logging.info(f"Loaded {len(allowed_777bigwin_ids)} users")
    except FileNotFoundError:
        logging.warning("users_777bigwin.json not found. Starting fresh")
        allowed_777bigwin_ids = set()
    except Exception as e:
        logging.error(f"Error loading users_777bigwin.json: {e}")
        allowed_777bigwin_ids = set()

def save_allowed_users():
    global allowed_777bigwin_ids
    try:
        with open('users_777bigwin.json', 'w') as f:
            json.dump({'allowed_ids': list(allowed_777bigwin_ids)}, f, indent=4)
            logging.info(f"Saved {len(allowed_777bigwin_ids)} users")
    except Exception as e:
        logging.error(f"Error saving user list: {e}")

def load_user_settings():
    """Load user settings from file"""
    global user_settings
    try:
        with open('user_settings.json', 'r') as f:
            user_settings = json.load(f)
            logging.info(f"Loaded user settings for {len(user_settings)} users")
    except FileNotFoundError:
        logging.warning("user_settings.json not found. Starting with empty settings")
        user_settings = {}
    except Exception as e:
        logging.error(f"Error loading user_settings.json: {e}")
        user_settings = {}

def save_user_settings():
    """Save user settings to file"""
    try:
        with open('user_settings.json', 'w') as f:
            json.dump(user_settings, f, indent=4)
            logging.info(f"Saved user settings for {len(user_settings)} users")
    except Exception as e:
        logging.error(f"Error saving user settings: {e}")

def get_default_user_settings():
    """Get default user settings with Entry Layer and SL support"""
    return {
        "strategy": "BS_ORDER",
        "betting_strategy": "Martingale",
        "game_type": "WINGO30S", 
        "martin_index": 0,
        "dalembert_units": 1,
        "pattern_index": 0,
        "running": False,
        "consecutive_losses": 0,
        "skip_betting": False,
        "virtual_mode": False,
        "bet_sizes": [100],
        "bs_wait_count": 0,
        "layer_limit": 1,  # Entry Layer: 1=Direct, 2=Wait for 1 lose, 3=Wait for 2 loses
        "entry_layer_state": None,
        "current_layer": 0,
        "original_martin_index": 0,
        "original_dalembert_units": 1,
        "original_custom_index": 0,
        "custom_index": 0,
        "sl_limit": None  # SL: Stop betting after consecutive losses and wait for win
    }

def normalize_text(text: str) -> str:
    return unicodedata.normalize('NFKC', text).strip()

def sign_md5(data: dict) -> str:
    filtered = {k: v for k, v in data.items() if k not in ("signature", "timestamp")}
    sort_map = dict(sorted(filtered.items()))
    json_str = json.dumps(sort_map, separators=(',', ':'))
    md5_hash = hashlib.md5(json_str.encode("utf-8")).hexdigest().upper()
    return md5_hash

def sign_md5_original(data: dict) -> str:
    data_copy = dict(data)
    data_copy.pop("signature", None)
    data_copy.pop("timestamp", None)
    s = json.dumps(dict(sorted(data_copy.items())), separators=(',', ':'))
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()

def compute_unit_amount(_amt: int) -> int:
    if _amt <= 0:
        return 1

    amt_str = str(_amt)
    trailing_zeros = len(amt_str) - len(amt_str.rstrip('0'))
    
    if trailing_zeros == 4:
        return 10000
    elif trailing_zeros == 3:
        return 1000
    elif trailing_zeros == 2:
        return 100
    elif trailing_zeros == 1:
        return 10
    else:
        length = len(amt_str)
        return 10 ** (length - 1)

def get_select_map():
    return {"B": 13, "S": 14}

def calculate_blockid_sum(block_id: str) -> int:
    digits = [int(c) for c in block_id if c.isdigit()]
    total = sum(digits)
    while total > 9:
        total = sum(int(d) for d in str(total))
    return total

def get_random_interval():
    if random.random() < 0.4:
        return random.randint(10, 20)
    return random.randint(20, 40)

async def acquire_command_lock(user_id: int) -> bool:
    if user_command_locks.get(user_id):
        return False
    user_command_locks[user_id] = True
    return True

def release_command_lock(user_id: int):
    user_command_locks.pop(user_id, None)

async def with_command_lock(user_id: int, fn):
    if not await acquire_command_lock(user_id):
        return {"success": False, "message": "🔄 Please wait, processing previous command..."}
    
    try:
        result = await fn()
        return {"success": True, "data": result}
    except Exception as error:
        logging.error(f"Command execution error for user {user_id}: {str(error)}")
        return {"success": False, "message": f"❌ Error: {str(error)}"}
    finally:
        release_command_lock(user_id)

def login_request(phone: str, password: str) -> (Optional[dict], Optional[requests.Session]):
    session = requests.Session()
    body = {
        "phonetype": -1, "language": 0, "logintype": "mobile",
        "random": "9078efc98754430e92e51da59eb2563c",
        "username": "95" + phone, "pwd": password
    }
    body["signature"] = sign_md5_original(body).upper()
    body["timestamp"] = int(time.time())
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; Mobile Build/QP1A.190711.020)",
        "Connection": "Keep-Alive", "Accept-Encoding": "gzip"
    }
    try:
        r = session.post(BASE_URL + "Login", headers=headers, json=body, timeout=12, verify=not IGNORE_SSL)
        res = r.json()
        if res.get("code") == 0 and "data" in res:
            token_header = res["data"].get("tokenHeader", "Bearer ")
            token = res["data"].get("token", "")
            session.headers.update({"Authorization": f"{token_header}{token}"})
            return res, session
        return res, None
    except Exception as e:
        logging.error(f"Login error: {e}")
        return {"error": str(e)}, None

async def get_user_info(session: requests.Session, user_id: int) -> Optional[dict]:
    body = {"language": 0, "random": "9078efc98754430e92e51da59eb2563c"}
    body["signature"] = sign_md5_original(body).upper()
    body["timestamp"] = int(time.time())
    try:
        r = session.post(BASE_URL + "GetUserInfo", json=body, timeout=12, verify=not IGNORE_SSL)
        res = r.json()
        if isinstance(res, dict) and res.get("code") == 0 and "data" in res:
            info = {
                "user_id": res["data"].get("userId"), "username": res["data"].get("userName"),
                "nickname": res["data"].get("nickName"), "balance": res["data"].get("amount"),
                "photo": res["data"].get("userPhoto"), "login_date": res["data"].get("userLoginDate"),
                "withdraw_count": res["data"].get("withdrawCount"),
                "is_allow_withdraw": res["data"].get("isAllowWithdraw", 0) == 1
            }
            user_game_info[user_id] = info
            return info
    except Exception as e:
        logging.error(f"Get user info error: {e}")
    return None

async def get_balance(session: requests.Session, user_id: int) -> Optional[float]:
    body = {"language": 0, "random": "9078efc6f3794bf49f257d07937d1a29"}
    body["signature"] = sign_md5_original(body).upper()
    body["timestamp"] = int(time.time())
    try:
        r = session.post(BASE_URL + "GetBalance", json=body, timeout=BALANCE_API_TIMEOUT, verify=not IGNORE_SSL)
        res = r.json()
        logging.info(f"Balance check response for user {user_id}: {res}")
        if isinstance(res, dict) and res.get("code") == 0 and "data" in res:
            data = res.get("data", {})
            amount = data.get("Amount") or data.get("amount") or data.get("balance")
            if amount is not None:
                if user_id in user_game_info:
                    user_game_info[user_id]["balance"] = float(amount)
                if user_id not in user_stats:
                    user_stats[user_id] = {"start_balance": float(amount), "profit": 0.0}
                return float(amount)
            logging.warning(f"No balance amount found for user {user_id}: {res}")
        else:
            logging.error(f"Get balance failed for user {user_id}: {res.get('msg', 'Unknown error')}")
    except Exception as e:
        logging.error(f"Balance check error for user {user_id}: {e}")
    return None

async def get_wingo_game_results(session: requests.Session) -> dict:
    """Get WINGO 30S game results"""
    body = {
        "pageSize": 10,
        "typeId": 30,
        "language": 7,
        "random": "6958cae52e234eb1967082c9b5a9c4ce",
        "signature": "88A0DADB43645500E64ADFFED763027E",
        "timestamp": int(time.time())
    }
    
    try:
        r = session.post(BASE_URL + "GetNoaverageEmerdList", json=body, timeout=12, verify=not IGNORE_SSL)
        res = r.json()
        logging.info(f"WINGO 30S results response: {res}")
        return res
    except Exception as e:
        logging.error(f"Error getting WINGO 30S results: {e}")
        return {"error": str(e)}

async def get_wingo_game_issue_request(session: requests.Session) -> dict:
    """Get WINGO 30S game issue"""
    body = {
        "typeId": 30,
        "language": 7,
        "random": "7d76f361dc5d4d8c98098ae3d48ef7af"
    }
    body["signature"] = sign_md5(body).upper()
    body["timestamp"] = int(time.time())
    
    try:
        r = session.post(BASE_URL + "GetGameIssue", json=body, timeout=12, verify=not IGNORE_SSL)
        res = r.json()
        logging.info(f"WINGO 30S game issue response: {res}")
        return res
    except Exception as e:
        logging.error(f"Error getting WINGO 30S game issue: {e}")
        return {"error": str(e)}

async def place_wingo_bet_request(session: requests.Session, issue_number: str, select_type: int, _amt: int, user_id: int) -> dict:
    """Place bet for WINGO 30S"""
    unit_amount = compute_unit_amount(_amt)
    bet_count = int(_amt / unit_amount) if unit_amount > 0 else 1
    
    betBody = {
        "typeId": 30,
        "issuenumber": issue_number,
        "language": 7,
        "gameType": 2,
        "amount": int(unit_amount),
        "betCount": int(bet_count),
        "selectType": select_type,
        "random": "f9ec46840a374a65bb2abad44dfc4dc3"
    }
    betBody["signature"] = sign_md5_original(betBody).upper()
    betBody["timestamp"] = int(time.time())
    
    endpoint = "GameBetting"
    
    for attempt in range(MAX_BET_RETRIES):
        try:
            r = session.post(BASE_URL + endpoint, json=betBody, timeout=BET_API_TIMEOUT, verify=not IGNORE_SSL)
            res = r.json()
            logging.info(f"WINGO 30S bet request for user {user_id}, issue {issue_number}, select_type {select_type}, amount {_amt}: {res}")
            return res
        except requests.exceptions.Timeout as e:
            logging.warning(f"WINGO 30S bet request timeout for user {user_id}, issue {issue_number}, attempt {attempt + 1}: {str(e)}")
            if attempt < MAX_BET_RETRIES - 1:
                await asyncio.sleep(BET_RETRY_DELAY)
                continue
            return {"error": f"WINGO 30S bet request timeout after {MAX_BET_RETRIES} attempts"}
        except Exception as e:
            logging.error(f"WINGO 30S place bet error for user {user_id}, issue {issue_number}, attempt {attempt + 1}: {str(e)}")
            if attempt < MAX_BET_RETRIES - 1:
                await asyncio.sleep(BET_RETRY_DELAY)
                continue
            return {"error": str(e)}
    return {"error": "Failed after retries"}

async def get_game_history(session: requests.Session, user_id: int) -> list:
    """Get game history for WINGO 30S"""
    body = {
        "pageSize": 10,
        "typeId": 30,
        "language": 7,
        "random": "f15bdcc4e6a04f82828b2f7a7b4c6e5a"
    }
    body["signature"] = sign_md5_original(body).upper()
    body["timestamp"] = int(time.time())
    
    try:
        r = session.post(BASE_URL + "GetNoaverageEmerdList", json=body, timeout=12, verify=not IGNORE_SSL)
        res = r.json()
        data = res.get("data", {}).get("list", [])
        logging.debug(f"Game history response for user {user_id}: {len(data)} records")
        
        valid_data = [item for item in data if item and item.get("number") is not None]
        logging.debug(f"Game history valid records: {len(valid_data)} out of {len(data)}")
        
        return valid_data
    except Exception as e:
        logging.error(f"Error fetching game history for user {user_id}: {e}")
        return []

async def send_message_with_retry(bot, chat_id: int, text: str, reply_markup=None):
    for attempt in range(MAX_TELEGRAM_RETRIES):
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            logging.info(f"Message sent to {chat_id}: {text}")
            return True
        except Exception as e:
            logging.error(f"Failed to send message to {chat_id}, attempt {attempt + 1}/{MAX_TELEGRAM_RETRIES}: {str(e)}")
            if attempt < MAX_TELEGRAM_RETRIES - 1:
                await asyncio.sleep(TELEGRAM_RETRY_DELAY)
                continue
            return False
    return False

def make_main_keyboard(logged_in: bool = False):
    if not logged_in:
        return ReplyKeyboardMarkup([["🔐 Login"]], resize_keyboard=True, one_time_keyboard=False)
    return ReplyKeyboardMarkup(
        [["⚔️ Start", "🛡️ Stop"], 
         ["🔢 Manual BS Order"],
         ["💣 Bet_Size", "🚀 Anti/Martingale"],
         ["🎯 Profit Target", "🛑 Stop Loss Limit"],
         ["🔄 Entry Layer", "⛔ SL"],
         ["🎮 Virtual/Real Mode"],
         ["🔐 Login", "🏁 Info"]],
        resize_keyboard=True, one_time_keyboard=False
    )
        
def make_entry_layer_keyboard():
    """Create inline keyboard for Entry Layer selection"""
    keyboard = [
        [InlineKeyboardButton("1 - Direct Bet", callback_data="entry_layer:1")],
        [InlineKeyboardButton("2 - Wait for 1 Lose", callback_data="entry_layer:2")],
        [InlineKeyboardButton("3 - Wait for 2 Loses", callback_data="entry_layer:3")],
        [InlineKeyboardButton("4 - Wait for 3 Loses", callback_data="entry_layer:4")],
        [InlineKeyboardButton("5 - Wait for 4 Loses", callback_data="entry_layer:5")],
        [InlineKeyboardButton("6 - Wait for 5 Loses", callback_data="entry_layer:6")],
        [InlineKeyboardButton("7 - Wait for 6 Loses", callback_data="entry_layer:7")],
        [InlineKeyboardButton("8 - Wait for 7 Loses", callback_data="entry_layer:8")],
        [InlineKeyboardButton("9 - Wait for 8 Loses", callback_data="entry_layer:9")],
        [InlineKeyboardButton("10 - Wait for 9 Loses", callback_data="entry_layer:10")]
    ]
    return InlineKeyboardMarkup(keyboard)

def make_mode_selection_keyboard():
    """Create inline keyboard for Virtual/Real mode selection"""
    keyboard = [
        [InlineKeyboardButton("🖥️ Virtual Mode", callback_data="mode:virtual")],
        [InlineKeyboardButton("💵 Real Mode", callback_data="mode:real")]
    ]
    return InlineKeyboardMarkup(keyboard)

def make_betting_strategy_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Anti-Martingale", callback_data="betting_strategy:Anti-Martingale")],
        [InlineKeyboardButton("Martingale", callback_data="betting_strategy:Martingale")],
        [InlineKeyboardButton("D'Alembert", callback_data="betting_strategy:D'Alembert")]
    ])

async def check_profit_and_stop_loss(user_id: int, bot, context: ContextTypes.DEFAULT_TYPE):
    """Check if profit target or stop loss has been reached"""
    settings = user_settings.get(user_id, {})
    target_profit = settings.get("target_profit")
    stop_loss = settings.get("stop_loss")
    
    if not target_profit and not stop_loss:
        return False
    
    current_profit = user_stats[user_id].get("profit", 0) if user_id in user_stats else 0
    
    if target_profit and current_profit >= target_profit:
        settings["running"] = False
        user_waiting_for_result.pop(user_id, None)
        user_should_skip_next.pop(user_id, None)
        
        # Reset betting strategy
        settings["martin_index"] = 0
        settings["dalembert_units"] = 1
        settings["custom_index"] = 0
        
        session = user_sessions.get(user_id)
        current_balance = await get_balance(session, user_id) if session else None
        balance_text = f"Final Balance: {current_balance:.2f} MMK\n" if current_balance is not None else ""
        
        message = f"🎯 PROFIT TARGET REACHED! 🎯\nTarget: {target_profit} MMK\nAchieved: {current_profit:.2f} MMK\n{balance_text}"
        
        await send_message_with_retry(bot, user_id, message, make_main_keyboard(True))
        user_stop_initiated[user_id] = True
        return True
    
    if stop_loss and current_profit <= -stop_loss:
        settings["running"] = False
        user_waiting_for_result.pop(user_id, None)
        user_should_skip_next.pop(user_id, None)
        
        # Reset betting strategy
        settings["martin_index"] = 0
        settings["dalembert_units"] = 1
        settings["custom_index"] = 0
        
        session = user_sessions.get(user_id)
        current_balance = await get_balance(session, user_id) if session else None
        balance_text = f"Final Balance: {current_balance:.2f} MMK\n" if current_balance is not None else ""
        
        message = f"🚫 STOP LOSS LIMIT REACHED! 🚫\nStop Loss Limit: {stop_loss} MMK\nCurrent Loss: {abs(current_profit):.2f} MMK\n{balance_text}"
        
        await send_message_with_retry(bot, user_id, message, make_main_keyboard(True))
        user_stop_initiated[user_id] = True
        return True
    
    return False

def update_betting_strategy(settings: dict, is_win: bool, bet_amount: float):
    """Update betting strategy based on win/loss"""
    betting_strategy = settings.get("betting_strategy", "Martingale")
    bet_sizes = settings.get("bet_sizes", [100])
    
    logging.debug(f"Updating betting strategy - Strategy: {betting_strategy}, Result: {'WIN' if is_win else 'LOSS'}, Bet Amount: {bet_amount}")
    
    if betting_strategy == "Martingale":
        if is_win:
            settings["martin_index"] = 0
            logging.info("Martingale: Win - Reset to index 0")
        else:
            settings["martin_index"] = min((settings.get("martin_index", 0) + 1, len(bet_sizes) - 1))
            logging.info(f"Martingale: Loss - Move to index {settings['martin_index']}")
    
    elif betting_strategy == "Anti-Martingale":
        if is_win:
            settings["martin_index"] = min((settings.get("martin_index", 0) + 1, len(bet_sizes) - 1))
            logging.info(f"Anti-Martingale: Win - Move to index {settings['martin_index']}")
        else:
            settings["martin_index"] = 0
            logging.info("Anti-Martingale: Loss - Reset to index 0")
    
    elif betting_strategy == "D'Alembert":
        if is_win:
            settings["dalembert_units"] = max(1, (settings.get("dalembert_units", 1) - 1))
            logging.info(f"D'Alembert: Win - Decrease units to {settings['dalembert_units']}")
        else:
            settings["dalembert_units"] = (settings.get("dalembert_units", 1) + 1)
            logging.info(f"D'Alembert: Loss - Increase units to {settings['dalembert_units']}")
    
    elif betting_strategy == "Custom":
        current_index = settings.get("custom_index", 0)
        
        # Find actual index based on bet amount
        actual_index = 0
        for i, size in enumerate(bet_sizes):
            if size == bet_amount:
                actual_index = i
                break
        
        if is_win:
            if actual_index > 0:
                settings["custom_index"] = actual_index - 1
            else:
                settings["custom_index"] = 0
            logging.info(f"Custom: Win - Move to index {settings['custom_index']}")
        else:
            if actual_index < len(bet_sizes) - 1:
                settings["custom_index"] = actual_index + 1
            else:
                settings["custom_index"] = len(bet_sizes) - 1
            logging.info(f"Custom: Loss - Move to index {settings['custom_index']}")

async def win_lose_checker(context: ContextTypes.DEFAULT_TYPE):
    """Enhanced win/lose checker with Entry Layer and SL support"""
    logging.info("Win/lose checker started for WINGO 30S with Entry Layer and SL support")
    while True:
        try:
            for user_id, session in list(user_sessions.items()):
                if not session:
                    continue
                
                settings = user_settings.get(user_id, {})
                if not settings:
                    continue
                
                # Get game results
                wingo_res = await get_wingo_game_results(session)
                if not wingo_res or wingo_res.get("code") != 0:
                    continue
                    
                data = wingo_res.get("data", {}).get("list", [])
                
                # Process pending bets (real bets)
                if user_id in user_pending_bets:
                    for period in list(user_pending_bets[user_id].keys()):
                        settled = next((item for item in data if item.get("issueNumber") == period), None)
                        
                        if settled and settled.get("number"):
                            bet_type, amount, is_virtual = user_pending_bets[user_id][period]
                            number = int(settled.get("number", "0")) % 10
                            big_small = "B" if number >= 5 else "S"
                            is_win = (bet_type == "B" and big_small == "B") or (bet_type == "S" and big_small == "S")
                            
                            # Update SL logic for REAL BETS
                            sl_limit = settings.get("sl_limit")
                            if sl_limit and sl_limit > 0 and not is_virtual:  # Only for real bets
                                if is_win:
                                    # Reset consecutive losses on win
                                    settings["consecutive_losses"] = 0
                                    settings["skip_betting"] = False
                                    user_sl_skip_waiting_for_win.pop(user_id, None)
                                    logging.info(f"SL: Real bet WIN detected for user {user_id}, resetting consecutive losses and resuming betting")
                                else:
                                    # Increment consecutive losses for real bets
                                    current_losses = settings.get("consecutive_losses", 0)
                                    settings["consecutive_losses"] = current_losses + 1
                                    logging.info(f"SL: Real bet LOSS detected for user {user_id}, consecutive losses: {current_losses + 1}")
                                    
                                    # Check if SL limit reached
                                    if current_losses + 1 >= sl_limit:
                                        settings["skip_betting"] = True
                                        user_sl_skip_waiting_for_win[user_id] = True
                                        logging.info(f"SL: Limit reached for user {user_id}, skipping real bets until win")
                            
                            # Update Entry Layer state
                            entry_layer = settings.get("layer_limit", 1)
                            entry_state = settings.get("entry_layer_state", {})
                            
                            if entry_layer == 2:
                                if is_win:
                                    entry_state["waiting_for_lose"] = True
                                else:
                                    entry_state["waiting_for_lose"] = False
                            elif entry_layer >= 3:
                                if is_win:
                                    entry_state["waiting_for_loses"] = True
                                    entry_state["consecutive_loses"] = 0
                                else:
                                    current_consecutive = entry_state.get("consecutive_loses", 0)
                                    entry_state["consecutive_loses"] = current_consecutive + 1
                                    wait_count = entry_layer - 1
                                    if current_consecutive + 1 >= wait_count:
                                        entry_state["waiting_for_loses"] = False
                            
                            settings["entry_layer_state"] = entry_state
                            
                            # Update betting strategy for both real and virtual bets
                            update_betting_strategy(settings, is_win, amount)
                            
                            # Update virtual or real balance
                            if is_virtual:
                                if user_id not in user_stats:
                                    user_stats[user_id] = {"virtual_balance": VIRTUAL_BALANCE}
                                if is_win:
                                    user_stats[user_id]["virtual_balance"] += amount * 0.96
                                else:
                                    user_stats[user_id]["virtual_balance"] -= amount
                            else:
                                if user_id in user_stats:
                                    if is_win:
                                        profit_change = amount * 0.96
                                        user_stats[user_id]["profit"] += profit_change
                                    else:
                                        user_stats[user_id]["profit"] -= amount
                            
                            # Check profit target and stop loss
                            bot_stopped = await check_profit_and_stop_loss(user_id, context.bot, context)
                            if bot_stopped:
                                del user_pending_bets[user_id][period]
                                if not user_pending_bets[user_id]:
                                    del user_pending_bets[user_id]
                                user_waiting_for_result[user_id] = False
                                continue
                            
                            # Get current balance
                            current_balance = None
                            if is_virtual:
                                current_balance = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE)
                            else:
                                current_balance = await get_balance(session, user_id)
                            
                            # Prepare result message
                            total_profit = 0
                            if is_virtual:
                                total_profit = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE) - VIRTUAL_BALANCE
                            else:
                                total_profit = user_stats[user_id].get("profit", 0) if user_id in user_stats else 0
                            
                            profit_indicator = "+" if total_profit > 0 else ("-" if total_profit < 0 else "")
                            
                            # Add SL info to message if applicable
                            sl_info = ""
                            sl_limit = settings.get("sl_limit")
                            if sl_limit and sl_limit > 0 and not is_virtual:
                                current_losses = settings.get("consecutive_losses", 0)
                                if settings.get("skip_betting", False):
                                    sl_info = f"\n\n⛔ SL ACTIVE: {current_losses}/{sl_limit} losses - Waiting for win"
                                else:
                                    sl_info = f"\n\n⛔ SL: {current_losses}/{sl_limit} losses"
                            
                            if is_win:
                                win_amount = amount * 0.96
                                bet_type_str = "VIRTUAL" if is_virtual else "REAL"
                                message = f"💚 {bet_type_str} WIN +{win_amount:.2f} MMK\n\n💸 Balance: {current_balance:.2f} MMK\n\n📈 Total Profit: {profit_indicator}{abs(total_profit):.2f} MMK\n\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_info}"
                            else:
                                bet_type_str = "VIRTUAL" if is_virtual else "REAL"
                                message = f"💔 {bet_type_str} LOSE -{amount:.2f} MMK\n\n💸 Balance: {current_balance:.2f} MMK\n\n📈 Total Profit: {profit_indicator}{abs(total_profit):.2f} MMK\n\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_info}"
                            
                            await send_message_with_retry(context.bot, user_id, message)
                            
                            # Clean up
                            del user_pending_bets[user_id][period]
                            if not user_pending_bets[user_id]:
                                del user_pending_bets[user_id]
                            user_waiting_for_result[user_id] = False
            
            # Process skipped bets (for Entry Layer and SL)
            for user_id, skipped_bets in list(user_skipped_bets.items()):
                if not skipped_bets:
                    continue
                    
                session = user_sessions.get(user_id)
                if not session:
                    continue
                    
                settings = user_settings.get(user_id, {})
                if not settings:
                    continue
                
                # Get game results
                wingo_res = await get_wingo_game_results(session)
                if not wingo_res or wingo_res.get("code") != 0:
                    continue
                    
                data = wingo_res.get("data", {}).get("list", [])
                
                for period in list(skipped_bets.keys()):
                    settled = next((item for item in data if item.get("issueNumber") == period), None)
                    
                    if settled and settled.get("number"):
                        bet_type, is_virtual = skipped_bets[period]
                        number = int(settled.get("number", "0")) % 10
                        big_small = "B" if number >= 5 else "S"
                        is_win = (bet_type == "B" and big_small == "B") or (bet_type == "S" and big_small == "S")
                        
                        # Update SL logic for SKIPPED BETS (virtual bets during SL period)
                        sl_limit = settings.get("sl_limit")
                        sl_resume_msg = ""
                        if sl_limit and sl_limit > 0 and settings.get("skip_betting", False):
                            if is_win:
                                # SL skip period win detected - resume real betting with current betting strategy
                                settings["consecutive_losses"] = 0
                                settings["skip_betting"] = False
                                user_sl_skip_waiting_for_win.pop(user_id, None)
                                logging.info(f"SL: Skip period WIN detected for user {user_id}, resetting consecutive losses and resuming REAL betting with current strategy")
                                
                                # Add special message for SL resume
                                sl_resume_msg = f"\n\n🎉 SL PERIOD ENDED - RESUMING REAL BETS! 🎉\nBetting Strategy: {settings.get('betting_strategy', 'Martingale')}"
                        
                        # Update Entry Layer state for skipped bets
                        entry_layer = settings.get("layer_limit", 1)
                        entry_state = settings.get("entry_layer_state", {})
                        
                        if entry_layer == 2:
                            if is_win:
                                entry_state["waiting_for_lose"] = True
                                message = f"🟢 SKIP WIN +0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                            else:
                                if entry_state.get("waiting_for_lose", True):
                                    entry_state["waiting_for_lose"] = False
                                message = f"🔴 SKIP LOSE -0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                                
                        elif entry_layer >= 3:
                            if is_win:
                                entry_state["waiting_for_loses"] = True
                                entry_state["consecutive_loses"] = 0
                                message = f"🟢 SKIP WIN +0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                            else:
                                current_consecutive = entry_state.get("consecutive_loses", 0)
                                entry_state["consecutive_loses"] = current_consecutive + 1
                                wait_count = entry_layer - 1
                                
                                if current_consecutive + 1 >= wait_count:
                                    entry_state["waiting_for_loses"] = False
                                    message = f"🔴 SKIP LOSE -0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                                else:
                                    remaining = wait_count - (current_consecutive + 1)
                                    message = f"🔴 SKIP LOSE -0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}\n⏳ Waiting for {remaining} more lose(s){sl_resume_msg}"
                        
                        else:
                            # For Entry Layer 1 or no entry layer, just show basic skip result
                            if is_win:
                                message = f"🟢 SKIP WIN +0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                            else:
                                message = f"🔴 SKIP LOSE -0 MMK\n🆔 WINGO30S: {period} =>{big_small}•{number}{sl_resume_msg}"
                        
                        settings["entry_layer_state"] = entry_state
                        
                        await send_message_with_retry(context.bot, user_id, message)
                        del user_skipped_bets[user_id][period]
                        
                        if user_skip_result_wait.get(user_id) == period:
                            del user_skip_result_wait[user_id]
            
            await asyncio.sleep(WIN_LOSE_CHECK_INTERVAL)
        except Exception as e:
            logging.error(f"Win/lose checker error: {e}")
            await asyncio.sleep(10)

def calculate_bet_amount(settings: dict, current_balance: float) -> float:
    """Calculate bet amount based on betting strategy"""
    betting_strategy = settings.get("betting_strategy", "Martingale")
    bet_sizes = settings.get("bet_sizes", [100])
    
    logging.debug(f"Calculating bet amount - Strategy: {betting_strategy}, Bet Sizes: {bet_sizes}")
    
    if betting_strategy == "D'Alembert":
        if len(bet_sizes) > 1:
            raise ValueError("D'Alembert strategy requires only ONE bet size")
        
        unit_size = bet_sizes[0]
        units = settings.get("dalembert_units", 1)
        amount = unit_size * units
        
        # Adjust if amount exceeds balance
        while amount > current_balance and units > 1:
            units -= 1
            amount = unit_size * units
        
        if amount > current_balance:
            amount = current_balance
        
        min_bet = min(bet_sizes)
        if amount < min_bet:
            amount = min_bet
            
        logging.info(f"D'Alembert: Betting {amount} ({units} units of {unit_size})")
        return amount
        
    elif betting_strategy == "Custom":
        custom_index = settings.get("custom_index", 0)
        adjusted_index = min(custom_index, len(bet_sizes) - 1)
        amount = bet_sizes[adjusted_index]
        logging.info(f"Custom: Betting {amount} at index {adjusted_index}")
        return amount
        
    else:  # Martingale or Anti-Martingale
        martin_index = settings.get("martin_index", 0)
        adjusted_index = min(martin_index, len(bet_sizes) - 1)
        amount = bet_sizes[adjusted_index]
        logging.info(f"{betting_strategy}: Betting {amount} at index {adjusted_index}")
        return amount

async def betting_worker(user_id: int, chat_id: int, app_context: ContextTypes.DEFAULT_TYPE):
    """Enhanced betting worker with Entry Layer and SL support"""
    settings = user_settings.get(user_id, {})
    session = user_sessions.get(user_id)
    
    if not settings or not session:
        logging.error(f"Betting worker failed for user {user_id}: No settings or session")
        await send_message_with_retry(app_context.bot, chat_id, "Please login first")
        if settings:
            settings["running"] = False
        return
    
    # Initialize user settings if not exists
    if user_id not in user_settings:
        user_settings[user_id] = get_default_user_settings()
    
    # Initialize stats
    if settings.get("virtual_mode", False):
        user_stats[user_id] = {"virtual_balance": VIRTUAL_BALANCE}
    else:
        user_stats[user_id] = {"start_balance": user_stats.get(user_id, {}).get("start_balance", 0.0), "profit": 0.0}
    
    # Initialize betting state
    settings["running"] = True
    settings["bet_time"] = {}
    settings["last_issue"] = None
    settings["consecutive_errors"] = 0
    settings["consecutive_losses"] = 0
    settings["skip_betting"] = False
    
    # Initialize Entry Layer state
    entry_layer = settings.get("layer_limit", 1)
    if entry_layer == 2:
        settings["entry_layer_state"] = {"waiting_for_lose": True}
    elif entry_layer >= 3:
        settings["entry_layer_state"] = {"waiting_for_loses": True, "consecutive_loses": 0}
    else:
        settings["entry_layer_state"] = {}
    
    user_should_skip_next[user_id] = False
    
    # Get initial balance
    current_balance = None
    if settings.get("virtual_mode", False):
        current_balance = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE)
    else:
        for attempt in range(MAX_BALANCE_RETRIES):
            current_balance = await get_balance(session, user_id)
            bet_sizes = settings.get("bet_sizes", [100])
            if not bet_sizes:
                logging.error(f"No bet sizes set for user {user_id}")
                await send_message_with_retry(app_context.bot, chat_id, "No bet sizes set. Please set BET SIZE first.")
                settings["running"] = False
                break
            if current_balance is not None and current_balance >= min(bet_sizes):
                settings["consecutive_errors"] = 0
                break
            logging.warning(f"Balance check failed for user {user_id}, attempt {attempt + 1}/{MAX_BALANCE_RETRIES}: {current_balance}")
            if attempt == MAX_BALANCE_RETRIES - 1:
                logging.error(f"Failed to get initial balance for user {user_id} after {MAX_BALANCE_RETRIES} attempts")
                await send_message_with_retry(app_context.bot, chat_id, "Failed to check balance. Stopping...")
                settings["running"] = False
                return
            await asyncio.sleep(BALANCE_RETRY_DELAY)
    
    if not settings["running"]:
        return
    
    # Prepare start message
    start_message = f"✅ BOT START\n\n"
    start_message += f"💠 Balance: {current_balance:.2f} MMK\n\n"
    start_message += f"🎯 Profit Target: {settings.get('target_profit', '0')} MMK\n"
    start_message += f"🛡️ Stop Loss: {settings.get('stop_loss', '0')} MMK\n"
    
    # Add SL info to start message
    sl_limit = settings.get("sl_limit")
    if sl_limit:
        start_message += f"⛔ SL Limit: {sl_limit} consecutive losses\n"
    
    if settings.get("betting_strategy"):
        betting_strategy_display = settings["betting_strategy"]
        start_message += f"🚀 Betting Strategy: {betting_strategy_display}\n"
    
    if settings.get("strategy"):
        strategy_display = settings["strategy"]
        start_message += f"🧠 Strategy: {strategy_display}"
    
    await send_message_with_retry(app_context.bot, chat_id, start_message)
    logging.info(f"Betting worker started for user {user_id}, game: WINGO 30S, settings: {settings}")
    
    try:
        while settings["running"]:
            if user_waiting_for_result.get(user_id, False):
                logging.debug(f"User {user_id} waiting for result, skipping cycle")
                await asyncio.sleep(1)
                continue

            # Get current balance
            if settings.get("virtual_mode", False):
                current_balance = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE)
            else:
                current_balance = await get_balance(session, user_id)
                if current_balance is None:
                    logging.warning(f"Failed to get balance for user {user_id}")
                    settings["consecutive_errors"] += 1
                    if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                        await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                        settings["running"] = False
                        break
                    await asyncio.sleep(5)
                    continue

            bet_sizes = settings.get("bet_sizes", [100])
            if not bet_sizes:
                logging.error(f"No bet sizes set for user {user_id}")
                await send_message_with_retry(app_context.bot, chat_id, "No bet sizes set. Please set BET SIZE first.")
                settings["running"] = False
                break
            
            min_bet_size = min(bet_sizes)
            if current_balance < min_bet_size:
                message = f"❌ Insufficient balance!\nCurrent Balance: {current_balance:.2f} MMK\nMinimum Bet Required: {min_bet_size} MMK\nPlease add funds to continue betting."
                await send_message_with_retry(app_context.bot, chat_id, message, make_main_keyboard(True))
                settings["running"] = False
                break
            
            # Get game issue
            issue_res = await get_wingo_game_issue_request(session)
                
            if not isinstance(issue_res, dict) or issue_res.get("code") != 0:
                logging.error(f"Game issue request failed for user {user_id}, WINGO 30S: {issue_res}")
                settings["consecutive_errors"] += 1
                if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                    logging.error(f"Max consecutive errors ({MAX_CONSECUTIVE_ERRORS}) reached for user {user_id}. Stopping bot.")
                    await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                    settings["running"] = False
                    break
                await asyncio.sleep(2)
                continue
            
            data = issue_res.get("data", {})
            current_issue = data.get("issueNumber")
                
            if not current_issue:
                logging.warning(f"No valid issue number for user {user_id}, WINGO 30S: {data}")
                settings["consecutive_errors"] += 1
                if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                    logging.error(f"Max consecutive errors ({MAX_CONSECUTIVE_ERRORS}) reached for user {user_id}. Stopping bot.")
                    await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                    settings["running"] = False
                    break
                await asyncio.sleep(1)
                continue
            
            if current_issue == settings.get("last_issue"):
                logging.debug(f"Same issue {current_issue} for user {user_id}, waiting for new issue")
                await asyncio.sleep(1)
                continue

            # Get prediction
            pattern = settings.get("pattern", DEFAULT_BS_ORDER)
            pattern_index = settings.get("pattern_index", 0)
            ch = pattern[pattern_index % len(pattern)]
            prediction = {"result": ch, "percent": "N/A"}
                
            ch = prediction["result"]
            select_type = get_select_map().get(ch)
            
            if select_type is None:
                logging.error(f"Invalid bet type {ch} for user {user_id}")
                settings["consecutive_errors"] += 1
                if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                    logging.error(f"Max consecutive errors ({MAX_CONSECUTIVE_ERRORS}) reached for user {user_id}. Stopping bot.")
                    await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                    settings["running"] = False
                    break
                await asyncio.sleep(2)
                continue
            
            # Check SL condition first (highest priority)
            sl_limit = settings.get("sl_limit")
            should_skip = False
            skip_reason = ""
            
            if sl_limit and sl_limit > 0 and settings.get("skip_betting", False):
                should_skip = True
                current_losses = settings.get("consecutive_losses", 0)
                skip_reason = f"⛔ SL ACTIVE: {current_losses}/{sl_limit} losses - Waiting for win"
            
            # Check Entry Layer condition only if not skipping due to SL
            if not should_skip:
                entry_layer = settings.get("layer_limit", 1)
                entry_state = settings.get("entry_layer_state", {})
                
                if entry_layer == 2:
                    if entry_state.get("waiting_for_lose", True):
                        should_skip = True
                        skip_reason = "Entry Layer 2: Waiting for 1 lose"
                elif entry_layer >= 3:
                    if entry_state.get("waiting_for_loses", True):
                        should_skip = True
                        current_consecutive = entry_state.get("consecutive_loses", 0)
                        wait_count = entry_layer - 1
                        skip_reason = f"Entry Layer {entry_layer}: Waiting for {wait_count} consecutive loses (current: {current_consecutive})"
            
            if should_skip:
                # Skip this bet
                bet_msg = f"🚨 {skip_reason}\n\n🆔 WINGO30S: {current_issue}\n🎯 BET: {'BIG' if ch == 'B' else 'SMALL'} ==> 0 MMK"
                
                if user_id not in user_skipped_bets:
                    user_skipped_bets[user_id] = {}
                user_skipped_bets[user_id][current_issue] = [ch, settings.get("virtual_mode", False)]
                
                user_skip_result_wait[user_id] = current_issue
                
                await send_message_with_retry(app_context.bot, chat_id, bet_msg)
                
                # Wait for result
                wait_attempts = 0
                max_wait_attempts = 60
                result_available = False
                
                while not result_available and wait_attempts < max_wait_attempts and settings["running"]:
                    await asyncio.sleep(1)
                    
                    if user_skip_result_wait.get(user_id) != current_issue:
                        result_available = True
                    
                    wait_attempts += 1
                
                if not result_available:
                    if user_skip_result_wait.get(user_id) == current_issue:
                        del user_skip_result_wait[user_id]
                
                settings["last_issue"] = current_issue
                await asyncio.sleep(1)
                continue
            
            # Calculate bet amount
            try:
                desired_amount = calculate_bet_amount(settings, current_balance)
            except ValueError as e:
                await send_message_with_retry(app_context.bot, chat_id, 
                    f"❌ {str(e)}\nPlease stop bot and set Bet Size again.",
                    make_main_keyboard(True)
                )
                settings["running"] = False
                break
            
            # Compute actual bet details
            unit_amount = compute_unit_amount(desired_amount)
            bet_count = max(1, int(desired_amount / unit_amount))
            actual_amount = unit_amount * bet_count
            
            if actual_amount == 0:
                await send_message_with_retry(app_context.bot, chat_id,
                    f"❌ Invalid bet amount: {desired_amount} MMK\nMinimum bet amount is {unit_amount} MMK\nPlease increase your bet size.",
                    make_main_keyboard(True)
                )
                settings["running"] = False
                break
            
            if current_balance < actual_amount:
                message = f"❌ Insufficient balance for next bet!\nCurrent Balance: {current_balance:.2f} MMK\nRequired Bet Amount: {actual_amount:.2f} MMK\nPlease add funds to continue betting."
                await send_message_with_retry(app_context.bot, chat_id, message, make_main_keyboard(True))
                settings["running"] = False
                break
            
            # Place bet
            bet_msg = f"🆔 WINGO30S: {current_issue}\n🎯 BET: {'BIG' if ch == 'B' else 'SMALL'} ==> {actual_amount:.2f} MMK"
            if prediction.get("percent"):
                bet_msg += f"\nConfidence: {prediction['percent']}%"
                
            # Add SL info to bet message
            sl_limit = settings.get("sl_limit")
            if sl_limit and sl_limit > 0:
                current_losses = settings.get("consecutive_losses", 0)
                bet_msg += f"\n⛔ SL: {current_losses}/{sl_limit} losses"
                
            await send_message_with_retry(app_context.bot, chat_id, bet_msg)
            logging.info(f"Placing bet for user {user_id}, WINGO 30S: {bet_msg}")
            
            if settings.get("virtual_mode", False):
                # Virtual bet
                if user_id not in user_pending_bets:
                    user_pending_bets[user_id] = {}
                user_pending_bets[user_id][current_issue] = [ch, actual_amount, True]
                user_waiting_for_result[user_id] = True
            else:
                # Real bet
                bet_resp = await place_wingo_bet_request(session, current_issue, select_type, actual_amount, user_id)
                    
                if isinstance(bet_resp, dict) and bet_resp.get("error"):
                    logging.error(f"Bet error for user {user_id}, WINGO 30S, issue {current_issue}: {bet_resp.get('error')}")
                    await send_message_with_retry(app_context.bot, chat_id, f"Bet error: {bet_resp.get('error')}. Retrying next cycle...")
                    settings["consecutive_errors"] += 1
                    if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                        logging.error(f"Max consecutive errors ({MAX_CONSECUTIVE_ERRORS}) reached for user {user_id}. Stopping bot.")
                        await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                        settings["running"] = False
                        break
                    await asyncio.sleep(5)
                    continue
                elif isinstance(bet_resp, dict) and bet_resp.get("code") != 0:
                    error_msg = bet_resp.get("msg", "Unknown error")
                    logging.error(f"API error for user {user_id}, WINGO 30S, issue {current_issue}: {error_msg}")
                    await send_message_with_retry(app_context.bot, chat_id, f"API error: {error_msg}. Retrying next cycle...")
                    settings["consecutive_errors"] += 1
                    if settings["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
                        logging.error(f"Max consecutive errors ({MAX_CONSECUTIVE_ERRORS}) reached for user {user_id}. Stopping bot.")
                        await send_message_with_retry(app_context.bot, chat_id, f"Too many consecutive errors ({MAX_CONSECUTIVE_ERRORS}). Stopping bot.")
                        settings["running"] = False
                        break
                    await asyncio.sleep(5)
                    continue
                
                settings["consecutive_errors"] = 0
                
                if user_id not in user_pending_bets:
                    user_pending_bets[user_id] = {}
                user_pending_bets[user_id][current_issue] = [ch, actual_amount, False]
                user_waiting_for_result[user_id] = True
            
            # Update state
            settings["last_issue"] = current_issue
            settings["pattern_index"] = (settings.get("pattern_index", 0) + 1) % len(settings.get("pattern", DEFAULT_BS_ORDER))
                
            logging.info(f"Placed bet for user {user_id}, WINGO 30S, waiting for result on issue {current_issue}")
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logging.info(f"Betting worker cancelled for user {user_id}")
    except Exception as e:
        logging.error(f"Betting worker error for user {user_id}, WINGO 30S: {e}")
        await send_message_with_retry(app_context.bot, chat_id, f"Betting error: {e}. Stopping...")
        settings["running"] = False
    finally:
        # Clean up
        settings["running"] = False
        user_waiting_for_result.pop(user_id, None)
        user_should_skip_next.pop(user_id, None)
        user_balance_warnings.pop(user_id, None)
        user_skip_result_wait.pop(user_id, None)
        
        # Reset betting strategy
        settings["martin_index"] = 0
        settings["dalembert_units"] = 1
        settings["custom_index"] = 0
        
        # Calculate final stats
        total_profit = 0
        balance_text = ""
        
        if settings.get("virtual_mode", False):
            total_profit = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE) - VIRTUAL_BALANCE
            balance_text = f"Virtual Balance: {user_stats[user_id].get('virtual_balance', VIRTUAL_BALANCE):.2f} MMK\n"
        else:
            total_profit = user_stats[user_id].get("profit", 0) if user_id in user_stats else 0
            session = user_sessions.get(user_id)
            current_balance = await get_balance(session, user_id) if session else None
            balance_text = f"Final Balance: {current_balance:.2f} MMK\n" if current_balance is not None else ""
        
        profit_indicator = "+" if total_profit > 0 else ("-" if total_profit < 0 else "")
        
        if not user_stop_initiated.get(user_id, False):
            message = f"🚫 BOT STOPPED\n{balance_text}💰 Total Profit: {profit_indicator}{abs(total_profit):.2f} MMK"
            await send_message_with_retry(app_context.bot, chat_id, message, make_main_keyboard(True))
        
        user_stop_initiated.pop(user_id, None)

async def check_user_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await send_message_with_retry(context.bot, update.effective_chat.id, "Please login first", reply_markup=make_main_keyboard(logged_in=False))
        return False
    if user_id not in user_settings:
        user_settings[user_id] = get_default_user_settings()
        logging.info(f"Initialized user_settings for user {user_id}")
    return True

async def cmd_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_settings:
        user_settings[user_id] = get_default_user_settings()
        logging.info(f"Initialized user_settings for user {user_id} in cmd_start_handler")
    logged_in = user_id in user_sessions
    await send_message_with_retry(context.bot, update.effective_chat.id, "Welcome to 777BigWin Bot for WINGO 30S!", reply_markup=make_main_keyboard(logged_in))

    if not hasattr(context.application, 'win_lose_task') or context.application.win_lose_task.done():
        context.application.win_lose_task = asyncio.create_task(win_lose_checker(context))

async def cmd_allow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await send_message_with_retry(context.bot, update.effective_chat.id, "Admin only!")
        return
    if not context.args or not context.args[0].isdigit():
        await send_message_with_retry(context.bot, update.effective_chat.id, "Usage: /allow {777bigwin_id}")
        return
    bigwin_id = int(context.args[0])
    if bigwin_id in allowed_777bigwin_ids:
        await send_message_with_retry(context.bot, update.effective_chat.id, f"User {bigwin_id} already added")
    else:
        allowed_777bigwin_ids.add(bigwin_id)
        save_allowed_users()
        await send_message_with_retry(context.bot, update.effective_chat.id, f"User {bigwin_id} added")

async def cmd_remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await send_message_with_retry(context.bot, update.effective_chat.id, "Admin only!")
        return
    if not context.args or not context.args[0].isdigit():
        await send_message_with_retry(context.bot, update.effective_chat.id, "Usage: /remove {777bigwin_id}")
        return
    bigwin_id = int(context.args[0])
    if bigwin_id not in allowed_777bigwin_ids:
        await send_message_with_retry(context.bot, update.effective_chat.id, f"User {bigwin_id} not found")
    else:
        allowed_777bigwin_ids.remove(bigwin_id)
        save_allowed_users()
        await send_message_with_retry(context.bot, update.effective_chat.id, f"User {bigwin_id} removed")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if not await check_user_authorized(update, context):
        return
    
    if query.data.startswith("betting_strategy:"):
        betting_strategy = query.data.split(":")[1]
        user_settings[user_id]["betting_strategy"] = betting_strategy
        
        # Reset betting strategy state
        user_settings[user_id]["martin_index"] = 0
        user_settings[user_id]["dalembert_units"] = 1
        user_settings[user_id]["consecutive_losses"] = 0
        user_settings[user_id]["skip_betting"] = False
        user_settings[user_id]["custom_index"] = 0
        
        save_user_settings()
        
        await send_message_with_retry(context.bot, query.message.chat_id, f"Betting Strategy set to: {betting_strategy}", reply_markup=make_main_keyboard(logged_in=True))
        await query.message.delete()
    
    elif query.data.startswith("entry_layer:"):
        layer_value = int(query.data.split(":")[1])
        user_settings[user_id]["layer_limit"] = layer_value
        
        # Initialize entry layer state
        if layer_value == 1:
            user_settings[user_id]["entry_layer_state"] = {}
        elif layer_value == 2:
            user_settings[user_id]["entry_layer_state"] = {"waiting_for_lose": True}
        elif layer_value >= 3:
            user_settings[user_id]["entry_layer_state"] = {"waiting_for_loses": True, "consecutive_loses": 0}
        
        save_user_settings()
        
        description = ""
        if layer_value == 1:
            description = "Bet immediately according to strategy"
        elif layer_value == 2:
            description = "Wait for 1 lose before betting"
        elif layer_value >= 3:
            wait_count = layer_value - 1
            description = f"Wait for {wait_count} consecutive loses before betting"
        
        await send_message_with_retry(context.bot, query.message.chat_id, f"Entry Layer set to: {layer_value} ({description})", reply_markup=make_main_keyboard(logged_in=True))
        await query.message.delete()
    
    elif query.data.startswith("mode:"):
        mode = query.data.split(":")[1]
        settings = user_settings[user_id]
        
        if mode == "virtual":
            settings["virtual_mode"] = True
            if user_id not in user_stats:
                user_stats[user_id] = {}
            if "virtual_balance" not in user_stats[user_id]:
                user_stats[user_id]["virtual_balance"] = VIRTUAL_BALANCE
            save_user_settings()
            await send_message_with_retry(context.bot, query.message.chat_id, f"🖥️ Switched to Virtual Mode ({VIRTUAL_BALANCE} MMK)", reply_markup=make_main_keyboard(logged_in=True))
        elif mode == "real":
            settings["virtual_mode"] = False
            save_user_settings()
            await send_message_with_retry(context.bot, query.message.chat_id, "💵 Switched to Real Mode", reply_markup=make_main_keyboard(logged_in=True))
        
        await query.message.delete()

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text
    text = normalize_text(raw_text)
    logging.info(f"Raw input by user {user_id}: {raw_text}")
    logging.info(f"Normalized input by user {user_id}: {text}")
    
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    logging.info(f"Parsed lines by user {user_id} (count: {len(lines)}): {lines}")
    logging.info(f"Current state for user {user_id}: {user_state.get(user_id, 'None')}")

    command = text.upper().replace('_', '').replace(' ', '').replace('/', '').replace('(', '').replace(')', '').replace('⛔', '').replace('🔢', '').replace('🛑', '').replace('🎯', '').replace('🔐', '').replace('🏁', '').replace('💣', '').replace('🚀', '').replace('⚔️', '').replace('🛡️', '').replace('🔄', '').replace('🎮', '')
    logging.info(f"Processed command for user {user_id}: {command}")

    if command == "LOGIN" or (lines and lines[0].lower() == "login"):
        if len(lines) >= 3 and lines[0].lower() == "login":
            username = lines[1]
            password = lines[2]
            logging.info(f"Processing login for user {user_id}: username={username}")
            await send_message_with_retry(context.bot, update.effective_chat.id, "Checking login...")
            res, session = login_request(username, password)
            if session:
                user_info = await get_user_info(session, user_id)
                if user_info and user_info.get("user_id"):
                    game_user_id = user_info.get("user_id")
                    if game_user_id not in allowed_777bigwin_ids:
                        logging.warning(f"Unauthorized login attempt for user {user_id}, game ID {game_user_id}")
                        session.close()
                        await send_message_with_retry(context.bot, update.effective_chat.id, "Unauthorized user ID. Contact admin to allow your ID.", reply_markup=make_main_keyboard(logged_in=False))
                        return
                    user_sessions[user_id] = session
                    user_game_info[user_id] = user_info
                    user_temp[user_id] = {"password": password}
                    balance = await get_balance(session, user_id)
                    user_stats[user_id] = {"start_balance": float(balance or 0), "profit": 0.0}
                    if user_id not in user_settings:
                        user_settings[user_id] = get_default_user_settings()
                        logging.info(f"Initialized user_settings for user {user_id} during login")
                    balance_display = balance if balance is not None else 0.0
                    await send_message_with_retry(context.bot, update.effective_chat.id, f"✅ Login Success, ID: {user_info['user_id']}, Balance: {balance_display:.2f} MMK", reply_markup=make_main_keyboard(logged_in=True))
                else:
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Login failed: Could not retrieve user info", reply_markup=make_main_keyboard(logged_in=False))
            else:
                msg = res.get("msg", "Login failed")
                await send_message_with_retry(context.bot, update.effective_chat.id, f"Login error: {msg}", reply_markup=make_main_keyboard(logged_in=False))
            user_state.pop(user_id, None)
            user_temp.pop(user_id, None)
            return
        if len(lines) == 1 and lines[0].lower() == "login":
            user_state[user_id] = {"state": "WAIT_PHONE"}
            await send_message_with_retry(context.bot, update.effective_chat.id, "Enter phone number or email:")
            return
        if user_state.get(user_id, {}).get("state") == "WAIT_PHONE":
            user_temp[user_id] = {"phone": text}
            user_state[user_id] = {"state": "WAIT_PASS"}
            await send_message_with_retry(context.bot, update.effective_chat.id, "Enter password:")
            return
        if user_state.get(user_id, {}).get("state") == "WAIT_PASS":
            phone = user_temp.get(user_id, {}).get("phone")
            password = text
            logging.info(f"Processing login for user {user_id}: username={phone}")
            await send_message_with_retry(context.bot, update.effective_chat.id, "Checking login...")
            res, session = login_request(phone, password)
            if session:
                user_info = await get_user_info(session, user_id)
                if user_info and user_info.get("user_id"):
                    game_user_id = user_info.get("user_id")
                    if game_user_id not in allowed_777bigwin_ids:
                        logging.warning(f"Unauthorized login attempt for user {user_id}, game ID {game_user_id}")
                        session.close()
                        await send_message_with_retry(context.bot, update.effective_chat.id, "Unauthorized user ID. Contact admin to allow your ID.", reply_markup=make_main_keyboard(logged_in=False))
                        return
                    user_sessions[user_id] = session
                    user_game_info[user_id] = user_info
                    user_temp[user_id] = {"password": password}
                    balance = await get_balance(session, user_id)
                    user_stats[user_id] = {"start_balance": float(balance or 0), "profit": 0.0}
                    if user_id not in user_settings:
                        user_settings[user_id] = get_default_user_settings()
                        logging.info(f"Initialized user_settings for user {user_id} during login")
                    balance_display = balance if balance is not None else 0.0
                    await send_message_with_retry(context.bot, update.effective_chat.id, f"✅ Login Success, ID: {user_info['user_id']}, Balance: {balance_display:.2f} MMK", reply_markup=make_main_keyboard(logged_in=True))
                else:
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Login failed: Could not retrieve user info", reply_markup=make_main_keyboard(logged_in=False))
            else:
                msg = res.get("msg", "Login failed")
                await send_message_with_retry(context.bot, update.effective_chat.id, f"Login error: {msg}", reply_markup=make_main_keyboard(logged_in=False))
            user_state.pop(user_id, None)
            user_temp.pop(user_id, None)
            return
        await send_message_with_retry(context.bot, update.effective_chat.id, "Enter login details as:\nLogin\n<phone>\n<password>")
        return
    
    if not await check_user_authorized(update, context) and command != "LOGIN":
        return
    
    try:
        if user_state.get(user_id, {}).get("state") == "INPUT_BET_SIZES":
            bet_sizes = [int(s) for s in lines[1:] if s.isdigit()]
            if not bet_sizes:
                raise ValueError("No valid numbers")
            
            settings = user_settings[user_id]
            if settings.get("betting_strategy") == "D'Alembert" and len(bet_sizes) > 1:
                await send_message_with_retry(context.bot, update.effective_chat.id, 
                    "❌ D'Alembert strategy requires only ONE bet size.\nPlease enter only one number for unit size.\nExample:\n100",
                    make_main_keyboard(logged_in=True)
                )
                return
            
            user_settings[user_id]["bet_sizes"] = bet_sizes
            user_settings[user_id]["dalembert_units"] = 1
            user_settings[user_id]["martin_index"] = 0
            user_settings[user_id]["custom_index"] = 0
            
            message = f"BET SIZE set: {', '.join(map(str, bet_sizes))} MMK"
            if settings.get("betting_strategy") == "D'Alembert":
                message += f"\n📝 D'Alembert Bet Size: {bet_sizes[0]} MMK"
            
            await send_message_with_retry(context.bot, update.effective_chat.id, message, reply_markup=make_main_keyboard(logged_in=True))
            user_state.pop(user_id, None)
        elif user_state.get(user_id, {}).get("state") == "INPUT_BET_ORDER":
            pattern = lines[1] if len(lines) >= 2 else text
            if all(c in "BS" for c in pattern.upper()) and pattern:
                user_settings[user_id]["pattern"] = pattern.upper()
                await send_message_with_retry(context.bot, update.effective_chat.id, f"BET ORDER set: {pattern.upper()}", reply_markup=make_main_keyboard(logged_in=True))
                user_state.pop(user_id, None)
            else:
                await send_message_with_retry(context.bot, update.effective_chat.id, "Invalid bet order. Use B or S as:\nBet_Order\nBSBBSSBSBBS", reply_markup=make_main_keyboard(logged_in=True))
        elif user_state.get(user_id, {}).get("state") == "INPUT_PROFIT_TARGET":
            target = float(lines[1] if len(lines) >= 2 else text)
            if target <= 0:
                raise ValueError
            user_settings[user_id]["target_profit"] = target
            await send_message_with_retry(context.bot, update.effective_chat.id, f"PROFIT TARGET set: {target:.2f} MMK", reply_markup=make_main_keyboard(logged_in=True))
            user_state.pop(user_id, None)
        elif user_state.get(user_id, {}).get("state") == "INPUT_STOP_LIMIT":
            stop_loss = float(lines[1] if len(lines) >= 2 else text)
            if stop_loss <= 0:
                raise ValueError
            user_settings[user_id]["stop_loss"] = stop_loss
            await send_message_with_retry(context.bot, update.effective_chat.id, f"STOP LOSS LIMIT set: {stop_loss:.2f} MMK", reply_markup=make_main_keyboard(logged_in=True))
            user_state.pop(user_id, None)
        elif user_state.get(user_id, {}).get("state") == "INPUT_SL_LIMIT":
            sl_limit = int(lines[1] if len(lines) >= 2 else text)
            if sl_limit < 0:
                raise ValueError("SL must be a non-negative integer")
            user_settings[user_id]["sl_limit"] = sl_limit if sl_limit > 0 else None
            user_settings[user_id]["consecutive_losses"] = 0
            user_settings[user_id]["skip_betting"] = False
            await send_message_with_retry(context.bot, update.effective_chat.id, f"SL set: {sl_limit if sl_limit is not None else ''} consecutive losses", reply_markup=make_main_keyboard(logged_in=True))
            user_state.pop(user_id, None)
        else:
            if command == "BETSIZE":
                user_state[user_id] = {"state": "INPUT_BET_SIZES"}
                await send_message_with_retry(context.bot, update.effective_chat.id, "Enter bet sizes as:\nBet_Size\n100\n200\n500", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "MANUALBSORDER":
                user_state[user_id] = {"state": "INPUT_BET_ORDER"}
                await send_message_with_retry(context.bot, update.effective_chat.id, "Enter bet order as:\nBet_Order\nBSBBSSBSBBS", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "PROFITTARGET":
                user_state[user_id] = {"state": "INPUT_PROFIT_TARGET"}
                await send_message_with_retry(context.bot, update.effective_chat.id, "Enter profit target as:\nProfit_Target\n100000", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "STOPLOSSLIMIT":
                user_state[user_id] = {"state": "INPUT_STOP_LIMIT"}
                await send_message_with_retry(context.bot, update.effective_chat.id, "Enter stop loss limit as:\nStop_Limit\n100000", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "SL":
                user_state[user_id] = {"state": "INPUT_SL_LIMIT"}
                await send_message_with_retry(context.bot, update.effective_chat.id, "Enter SL as:\nSL\n3\n(0 to disable)", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "ENTRYLAYER":
                await send_message_with_retry(context.bot, update.effective_chat.id, "Select Entry Layer:", reply_markup=make_entry_layer_keyboard())
            elif command == "VIRTUALREALMODE":
                await send_message_with_retry(context.bot, update.effective_chat.id, "Select Mode:", reply_markup=make_mode_selection_keyboard())
            elif command in ["ANTIMARTINGALE", "🚀ANTI/MARTINGALE"]:
                await send_message_with_retry(context.bot, update.effective_chat.id, "Choose Betting Strategy:", reply_markup=make_betting_strategy_keyboard())
            elif command in ["🎮WINGO30S", "GAME", "GAMETYPE"]:
                await send_message_with_retry(context.bot, update.effective_chat.id, "Game type set to: WINGO 30S", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "START":
                settings = user_settings.get(user_id, {})
                logging.info(f"Start command for user {user_id}, settings: {settings}")
                if not settings.get("bet_sizes") or not settings.get("pattern"):
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Set BET SIZE and BET ORDER first!", reply_markup=make_main_keyboard(logged_in=True))
                    return
                if settings.get("betting_strategy") == "D'Alembert" and len(settings.get("bet_sizes", [])) > 1:
                    await send_message_with_retry(context.bot, update.effective_chat.id, "D'Alembert requires a single BET SIZE. Please set one bet size.", reply_markup=make_main_keyboard(logged_in=True))
                    return
                if settings.get("running"):
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Bot already running!", reply_markup=make_main_keyboard(logged_in=True))
                    return
                
                # Initialize betting state
                settings["martin_index"] = 0
                settings["dalembert_units"] = 1
                settings["pattern_index"] = 0
                settings["consecutive_losses"] = 0
                settings["skip_betting"] = False
                settings["running"] = True
                settings["consecutive_errors"] = 0
                
                # Initialize Entry Layer state
                entry_layer = settings.get("layer_limit", 1)
                if entry_layer == 2:
                    settings["entry_layer_state"] = {"waiting_for_lose": True}
                elif entry_layer >= 3:
                    settings["entry_layer_state"] = {"waiting_for_loses": True, "consecutive_loses": 0}
                else:
                    settings["entry_layer_state"] = {}
                
                user_waiting_for_result[user_id] = False
                user_should_skip_next[user_id] = False
                
                task = asyncio.create_task(betting_worker(user_id, update.effective_chat.id, context))
                settings["task"] = task
            elif command == "STOP":
                settings = user_settings.get(user_id, {})
                if not settings.get("running"):
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Bot not running!", reply_markup=make_main_keyboard(logged_in=True))
                    return
                
                user_stop_initiated[user_id] = True
                settings["running"] = False
                if settings.get("task"):
                    settings["task"].cancel()
                    settings["task"] = None
                
                user_waiting_for_result.pop(user_id, None)
                user_should_skip_next.pop(user_id, None)
                
                # Reset betting strategy
                settings["martin_index"] = 0
                settings["dalembert_units"] = 1
                settings["custom_index"] = 0
                
                session = user_sessions.get(user_id)
                current_balance = await get_balance(session, user_id) if session else None
                balance_text = f"Balance: {current_balance:.2f} MMK\n" if current_balance is not None else ""
                await send_message_with_retry(context.bot, update.effective_chat.id, f"Bot stopped!\n{balance_text}", reply_markup=make_main_keyboard(logged_in=True))
            elif command == "INFO":
                session = user_sessions.get(user_id)
                user_info = await get_user_info(session, user_id) if session else None
                if not user_info:
                    await send_message_with_retry(context.bot, update.effective_chat.id, "Failed to get info", reply_markup=make_main_keyboard(logged_in=True))
                    return
                balance = await get_balance(session, user_id) if session else None
                settings = user_settings.get(user_id, {})
                bet_sizes = settings.get("bet_sizes", [])
                bet_order = settings.get("pattern", "")
                profit_target = settings.get("target_profit")
                stop_loss = settings.get("stop_loss")
                sl_limit = settings.get("sl_limit")
                betting_strategy = settings.get("betting_strategy", "Martingale")
                game_type = settings.get("game_type", "WINGO30S")
                virtual_mode = settings.get("virtual_mode", False)
                layer_limit = settings.get("layer_limit", 1)
                
                # Calculate current profit
                current_profit = 0
                if virtual_mode:
                    current_profit = user_stats[user_id].get("virtual_balance", VIRTUAL_BALANCE) - VIRTUAL_BALANCE
                else:
                    current_profit = user_stats[user_id].get("profit", 0) if user_id in user_stats else 0
                
                profit_indicator = "+" if current_profit > 0 else ("-" if current_profit < 0 else "")
                
                info_text = (
                    f"🆔 User ID: {user_info.get('user_id', 'N/A')}\n"
                    f"💰 Balance: {balance:.2f} MMK\n"
                    f"🎮 Game: {game_type}\n"
                    f"🧠 Strategy: BS_ORDER\n"
                    f"💵 Betting Strategy: {betting_strategy}\n"
                    f"💸 Bet Sizes: {', '.join(map(str, bet_sizes)) if bet_sizes else ''}\n"
                    f"🔢 Bet Order: {bet_order}\n"
                    f"🎯 Profit Target: {f'{profit_target:.2f} MMK' if isinstance(profit_target, (int, float)) else ''}\n"
                    f"🛑 Stop Loss: {f'{stop_loss:.2f} MMK' if isinstance(stop_loss, (int, float)) else ''}\n"
                    f"⛔ SL Limit: {sl_limit if sl_limit is not None else ''}\n"
                    f"🔄 Entry Layer: {layer_limit if layer_limit is not None else ''}\n"
                    f"🚀 Running: {'Yes' if settings.get('running', False) else 'No'}"
                )
                await send_message_with_retry(context.bot, update.effective_chat.id, info_text, reply_markup=make_main_keyboard(logged_in=True))
    except ValueError as e:
        await send_message_with_retry(context.bot, update.effective_chat.id, f"Invalid input: {str(e)}", reply_markup=make_main_keyboard(logged_in=True))
    except Exception as e:
        logging.error(f"Error handling input for user {user_id}: {str(e)}")
        await send_message_with_retry(context.bot, update.effective_chat.id, f"Error: {str(e)}", reply_markup=make_main_keyboard(logged_in=True))

def main():
    load_allowed_users()
    load_user_settings()
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start_handler))
    application.add_handler(CommandHandler("allow", cmd_allow_handler))
    application.add_handler(CommandHandler("remove", cmd_remove_handler))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()