import os
import base58
import hashlib
from tqdm import tqdm
from ecdsa import SigningKey, SECP256k1
from bitcoinlib.keys import Key
import time
import sys
from datetime import datetime
import requests
import json
import random
import math
import multiprocessing
# import concurrent.futures # Not used in this structure

# =================================================================
# GLOBAL CONFIGURATION AND OPTIMIZATION SETTINGS
# =================================================================

# Global variables for stats
total_matches_found = 0
found_file = "found.txt"
check_balance = True
balance_mode = "quick"  # quick, verified, or none
request_timeout = 30  
max_retries = 3

# Multiprocessing Configuration (CPU Limit)
TOTAL_CORES = os.cpu_count() if os.cpu_count() else 4
NUM_PROCESSES = max(1, math.floor(TOTAL_CORES * 0.75)) # Limit CPU usage to ~75%
print(f"INFO: Total cores: {TOTAL_CORES}. Initial processes set to {NUM_PROCESSES}.")

# Variables for Shared Memory (Crucial for OOM fix)
SHARED_TARGET_DATA = None 
SHARED_MIN_MATCH_LENGTH = 0

# Proxy Configuration
USE_PROXY = False
PROXY_HOST = ""
PROXY_PORT = ""
PROXY_USER = ""
PROXY_PASS = ""
_PROXIES = None 

# Telegram Configuration
TELEGRAM_API_KEY = "7499524081:AAFgDfCsQQiaSyXXtaH-vtJLnJN_rG4iEz8"
TELEGRAM_CHAT_ID = "828721892"
USE_TELEGRAM = False # Will be set to True if balance check is enabled and confirmed by user

# Daftar User-Agent 
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.43 Mobile Safari/537.36',
]

# =================================================================
# SHARED MEMORY INITIALIZER
# =================================================================

def init_worker(target_data, min_match_length):
    """Fungsi ini dipanggil saat setiap proses worker dimulai untuk memuat data target ke memori bersama."""
    global SHARED_TARGET_DATA, SHARED_MIN_MATCH_LENGTH
    SHARED_TARGET_DATA = target_data
    SHARED_MIN_MATCH_LENGTH = min_match_length

# =================================================================
# UTILITY FUNCTIONS
# =================================================================

def random_private_key():
    return int.from_bytes(os.urandom(32), byteorder='big') % SECP256k1.order

def generate_bitcoin_addresses(private_key_hex):
    private_key_bytes = bytes.fromhex(private_key_hex)
    signing_key = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    public_key_uncompressed = signing_key.get_verifying_key().to_string("uncompressed")
    public_key_compressed = signing_key.get_verifying_key().to_string("compressed")
    
    def create_address(public_key_bytes):
        sha256_hash = hashlib.sha256(public_key_bytes).digest()
        ripemd160_hash = hashlib.new('ripemd160', sha256_hash).digest()
        versioned_payload = b'\x00' + ripemd160_hash
        checksum = hashlib.sha256(hashlib.sha256(versioned_payload).digest()).digest()[:4]
        address = base58.b58encode(versioned_payload + checksum).decode()
        return address
    
    return create_address(public_key_compressed), create_address(public_key_uncompressed)

def load_target_addresses(filename="P2PKH_All.txt", min_match_length=3):
    target_data = {'compressed': {}, 'uncompressed': {}}
    
    try:
        print(f"DEBUG: Loading addresses from {filename}...")
        with open(filename, 'r') as f:
            lines = f.readlines()
        
        for line in tqdm(lines, desc="Loading targets", unit="lines"):
            line = line.strip()
            if line and not line.startswith('#'):
                address = line.split()[0] if ' ' in line else line
                
                current_prefix_len = min(len(address), min_match_length)
                prefix = address[:current_prefix_len]
                
                if prefix not in target_data['compressed']:
                    target_data['compressed'][prefix] = []
                target_data['compressed'][prefix].append(address)
                
                if prefix not in target_data['uncompressed']:
                    target_data['uncompressed'][prefix] = []
                target_data['uncompressed'][prefix].append(address)
        
        return target_data
        
    except FileNotFoundError:
        print(f"ERROR: File {filename} tidak ditemukan!")
        return None

def check_matches(address_compressed, address_uncompressed, target_data, min_match_length):
    matches = []
    
    prefix_comp = address_compressed[:min_match_length]
    if prefix_comp in target_data['compressed']:
        for target in target_data['compressed'][prefix_comp]:
            matches.append({'address': address_compressed, 'target': target, 'match_length': min_match_length, 'type': 'compressed', 'prefix': prefix_comp})
            
    prefix_uncomp = address_uncompressed[:min_match_length]
    if prefix_uncomp in target_data['uncompressed']:
        for target in target_data['uncompressed'][prefix_uncomp]:
            matches.append({'address': address_uncompressed, 'target': target, 'match_length': min_match_length, 'type': 'uncompressed', 'prefix': prefix_uncomp})
    
    return matches

# =================================================================
# WORKER FUNCTION (Uses Shared Data)
# =================================================================

def worker_search():
    """Worker function for parallel key generation and matching, using globally shared data."""
    global SHARED_TARGET_DATA, SHARED_MIN_MATCH_LENGTH
    
    target_data = SHARED_TARGET_DATA
    min_match_length = SHARED_MIN_MATCH_LENGTH

    if target_data is None:
        return {'attempts': 0, 'match_info': None, 'private_key': None}

    local_attempts = 0
    
    while True:
        private_key = random_private_key()
        private_key_hex = private_key.to_bytes(32, byteorder='big').hex()
        addr_comp, addr_uncomp = generate_bitcoin_addresses(private_key_hex)
        local_attempts += 1
        
        found_matches = check_matches(addr_comp, addr_uncomp, target_data, min_match_length)
        
        if found_matches:
            return {
                'private_key': private_key,
                'match_info': found_matches[0],
                'attempts': local_attempts
            }

        # Return a status update after 1 million attempts for progress tracking
        if local_attempts % 1000000 == 0:
            return {'attempts': local_attempts, 'match_info': None, 'private_key': None}

# =================================================================
# PROXY & BALANCE CHECK FUNCTIONS 
# =================================================================

def setup_proxy():
    global _PROXIES
    if not USE_PROXY or not PROXY_HOST or not PROXY_PORT:
        _PROXIES = None
        return None

    if PROXY_USER and PROXY_PASS:
        auth = f"{PROXY_USER}:{PROXY_PASS}@"
    else:
        auth = ""

    # SOCKS5 assumed for high-performance rotating proxies
    proxy_url = f"socks5://{auth}{PROXY_HOST}:{PROXY_PORT}"
    
    _PROXIES = {
        "http": proxy_url,
        "https": proxy_url,
    }
    return _PROXIES

def check_balance_quick(address):
    global _PROXIES
    for retry in range(max_retries):
        try:
            url = f"https://blockchain.info/balance?active={address}"
            headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
            
            response = requests.get(
                url, headers=headers, timeout=request_timeout, proxies=_PROXIES 
            )
            
            if response.status_code == 200:
                data = response.json()
                if address in data:
                    return data[address]['final_balance'] / 100000000
                return 0
            elif response.status_code == 429: time.sleep(2 * (retry + 1)); continue
            elif response.status_code == 400: return 0 
                
        except Exception:
            if retry < max_retries - 1: time.sleep(1); continue
            return "Error: Check failed"
    return "Check failed"

def check_balance_verified(address):
    global _PROXIES
    sources_results = []
    
    def fetch_balance(url, parser_func, source_name):
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            resp = requests.get(
                url, headers=headers, timeout=request_timeout, proxies=_PROXIES
            )
            if resp.status_code == 200:
                data = resp.json()
                return parser_func(data, address)
        except Exception:
            return None

    bal1 = fetch_balance(f"https://blockchain.info/balance?active={address}",
        lambda data, addr: data[addr]['final_balance'] / 100000000 if addr in data else 0, "Blockchain.info")
    if bal1 is not None: sources_results.append(("Blockchain.info", bal1))
    time.sleep(0.5)
    
    bal2 = fetch_balance(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}",
        lambda data, addr: data['data'][addr]['address']['balance'] / 100000000 if 'data' in data and addr in data['data'] else 0, "Blockchair")
    if bal2 is not None: sources_results.append(("Blockchair", bal2))
    time.sleep(0.5)
    
    bal3 = fetch_balance(f"https://api.blockcypher.com/v1/btc/main/addrs/{address}/balance",
        lambda data, addr: data['final_balance'] / 100000000 if 'final_balance' in data else 0, "Blockcypher")
    if bal3 is not None: sources_results.append(("Blockcypher", bal3))
    
    if not sources_results: return "No sources responded"
    
    balances = [bal for _, bal in sources_results]
    
    if len(balances) >= 2:
        max_diff = max(balances) - min(balances)
        if max_diff < 0.00001: 
            return {'balance': sum(balances) / len(balances), 'sources': len(sources_results), 'details': sources_results, 'status': 'VERIFIED'}
        else:
            return {'balance': sum(balances) / len(balances), 'sources': len(sources_results), 'details': sources_results, 'status': 'INCONSISTENT', 'max_diff': max_diff}
    else:
        return {'balance': balances[0], 'sources': 1, 'details': sources_results, 'status': 'SINGLE_SOURCE'}

def check_balance_main(address, mode="quick"):
    if mode == "none": return None
    print(f"[Balance] Checking {address[:12]}...")
    
    if mode == "quick":
        result = check_balance_quick(address)
        if isinstance(result, (int, float)):
            return {'balance': result, 'sources': 1, 'status': 'QUICK_CHECK'}
        else:
            return {'balance': 0, 'sources': 0, 'status': f'ERROR: {result}'}
    
    elif mode == "verified":
        return check_balance_verified(address)

# =================================================================
# TELEGRAM NOTIFICATION FUNCTION
# =================================================================

def send_telegram_notification(message):
    global _PROXIES
    if not USE_TELEGRAM or not TELEGRAM_API_KEY or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_API_KEY}/sendMessage"
    
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    
    headers = {'User-Agent': random.choice(USER_AGENTS)}

    try:
        requests.post(
            url, 
            json=payload, 
            headers=headers, 
            timeout=10, 
            proxies=_PROXIES 
        )
        print("[Telegram] Notification sent.")
        return True
    except Exception as e:
        print(f"[Telegram] Warning: Failed to send notification: {e}")
        return False

# =================================================================
# SAVE AND DISPLAY FUNCTIONS
# =================================================================

def save_to_found_file(private_key, match_info, attempts, search_time, match_num, balance_result=None):
    global total_matches_found
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(found_file, "a", encoding="utf-8") as f:
        f.write(f"MATCH #{match_num} | {timestamp} | Type: {match_info['type']} | Match: {match_info['match_length']}\n")
        f.write(f"Address: {match_info['address']}\n")
        f.write(f"Target:  {match_info['target']}\n")
        f.write(f"Private: {hex(private_key)}\n")
        
        try:
            key_obj = Key(hex(private_key)[2:])
            wif_compressed = key_obj.wif()
            key_obj_uncomp = Key(hex(private_key)[2:], compressed=False)
            wif_uncompressed = key_obj_uncomp.wif()
            
            if match_info['type'] == 'compressed':
                f.write(f"WIF (compressed): {wif_compressed}\n")
            else:
                f.write(f"WIF (uncompressed): {wif_uncompressed}\n")
        except Exception as e:
            f.write(f"WIF Error: {str(e)}\n")
        
        if balance_result:
            f.write(f"\n--- BALANCE INFORMATION ---\n")
            
            if isinstance(balance_result, dict):
                balance_value = balance_result.get('balance', 0)
                sources = balance_result.get('sources', 0)
                status = balance_result.get('status', 'UNKNOWN')
                
                f.write(f"Balance: {balance_value:.8f} BTC\n")
                f.write(f"Sources: {sources}\n")
                f.write(f"Status: {status}\n")
                
                if 'details' in balance_result:
                    f.write(f"Details:\n")
                    for source_name, bal in balance_result['details']:
                        f.write(f"  - {source_name}: {bal:.8f} BTC\n")
                
                if balance_value > 0:
                    f.write(f"\n⚠️  ⚠️  ⚠️  NON-ZERO BALANCE FOUND! ⚠️  ⚠️  ⚠️\n")
                    f.write(f"💰 AMOUNT: {balance_value:.8f} BTC 💰\n")
                    f.write(f"🔗 Explorer: https://www.blockchain.com/explorer/addresses/btc/{match_info['address']}\n")
                    f.write(f"🔗 Alternative: https://blockchair.com/bitcoin/address/{match_info['address']}\n")
                    f.write(f"🔊 ALERT: Telegram notification sent\n")
            else:
                f.write(f"Balance Result: {balance_result}\n")
        else:
            f.write(f"\nBalance: Not checked\n")
        
        f.write(f"\nAttempts: {attempts:,}\n")
        f.write(f"Search Time: {search_time:.1f} seconds\n")
        f.write("-" * 70 + "\n\n")
    
    total_matches_found += 1

# =================================================================
# MAIN SEARCH LOOP
# =================================================================

def find_multi_vanity_address(target_data, min_match_length):
    global total_matches_found, USE_TELEGRAM
    attempts = 0
    matches_found_in_session = 0
    start_time = time.time()
    
    print(f"\nSearching with prefix length: {min_match_length}...")
    print(f"Balance Mode: {balance_mode.upper()} | Processes: {NUM_PROCESSES}")
    
    with multiprocessing.Pool(
        processes=NUM_PROCESSES,
        initializer=init_worker,
        initargs=(target_data, min_match_length)
    ) as pool:
        
        async_results = [
            pool.apply_async(worker_search)
            for _ in range(NUM_PROCESSES)
        ]
        
        try:
            while True:
                ready_indices = []
                for i, result in enumerate(async_results):
                    if result.ready():
                        ready_indices.append(i)
                
                if not ready_indices:
                    time.sleep(0.01)
                    continue
                
                for i in ready_indices:
                    result = async_results[i].get()
                    
                    attempts += result['attempts']
                    
                    if result['match_info']:
                        # --- Match Found ---
                        search_time = time.time() - start_time
                        matches_found_in_session += 1
                        match_info = result['match_info']
                        private_key = result['private_key']
                        
                        # Balance Check (I/O - Main Thread)
                        balance_result = None
                        if balance_mode != "none":
                            balance_result = check_balance_main(match_info['address'], balance_mode)
                        
                        # Prepare balance values
                        balance_value = 0
                        status = "N/A"
                        if balance_result and isinstance(balance_result, dict):
                            balance_value = balance_result.get('balance', 0)
                            status = balance_result.get('status', '')
                            
                        # Save to file
                        save_to_found_file(private_key, match_info, attempts, search_time, matches_found_in_session, balance_result)
                        
                        # --- TELEGRAM NOTIFICATION ---
                        if balance_value > 0 and USE_TELEGRAM:
                            try:
                                key_obj = Key(hex(private_key)[2:])
                                wif_compressed = key_obj.wif()
                            except Exception:
                                wif_compressed = "WIF generation failed"
                            
                            notification_message = (
                                f"🚨 *BTC VANITY MATCH FOUND WITH BALANCE* 🚨\n\n"
                                f"🎯 Target Match: `{match_info['target']}`\n"
                                f"🔗 Address: `{match_info['address']}`\n"
                                f"💰 *Balance*: `{balance_value:.8f} BTC`\n"
                                f"🔍 Status: {status}\n\n"
                                f"🔑 Private Key (Hex): `0x{hex(private_key)[2:]}`\n"
                                f"🔑 WIF (Compressed): `{wif_compressed}`\n\n"
                                f"Explorer: [Check Balance](https://www.blockchain.com/explorer/addresses/btc/{match_info['address']})"
                            )
                            send_telegram_notification(notification_message)

                        # Display output to console
                        print(f"\n{'='*60}"); print(f"[!] MATCH #{matches_found_in_session} FOUND! | Attempts: {attempts:,}")
                        print(f"{'='*60}"); print(f"Address: {match_info['address']}"); print(f"Target:  {match_info['target']}")

                        if balance_mode != "none":
                            if balance_value > 0:
                                print(f"\n⚠️  💰 BALANCE FOUND: {balance_value:.8f} BTC 💰"); print(f"   Status: {status}")
                            else:
                                print(f"\nBalance: {balance_value:.8f} BTC (Empty)"); print(f"Status: {status}")
                        
                        print(f"{'='*60}")

                    # Submit a new job 
                    async_results[i] = pool.apply_async(worker_search)
                
                # Update progress
                if time.time() - start_time > 1:
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        speed = attempts / elapsed
                        sys.stdout.write(f"\rAttempts: {attempts:,} | Speed: {speed:.0f} keys/s | Matches: {matches_found_in_session}")
                        sys.stdout.flush()
    
        except KeyboardInterrupt:
            print(f"\n\n{'='*60}")
            print("Session Summary:")
            print(f"{'='*60}")
            pool.terminate()
            pool.join()
            
            if attempts > 0 and time.time() - start_time > 0:
                elapsed = time.time() - start_time
                speed = attempts / elapsed
                print(f"Total Attempts: {attempts:,}"); print(f"Total Matches: {matches_found_in_session}")
                print(f"Average Speed: {speed:.0f} keys/s"); print(f"Elapsed Time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
            
            return matches_found_in_session

# =================================================================
# MAIN EXECUTION
# =================================================================

def initialize_found_file(prefix_len, mode):
    if not os.path.exists(found_file):
        with open(found_file, "w") as f:
            f.write(f"{'='*70}\n")
            f.write(f"VANITY ADDRESS SEARCH (OOM-Resistant & Telegram Notif)\n")
            f.write(f"{'='*70}\n")
            f.write(f"START TIME: {datetime.now()}\n")
            f.write(f"PREFIX LENGTH: {prefix_len}\n")
            f.write(f"BALANCE MODE: {mode.upper()}\n")
            f.write(f"CPU PROCESSES: {NUM_PROCESSES}/{TOTAL_CORES} (75% limit)\n")
            f.write(f"{'-'*70}\n\n")

def main():
    global check_balance, balance_mode, request_timeout, max_retries, USE_TELEGRAM
    
    print("=" * 70); print("VANITY ADDRESS SEARCH (Optimized)")
    print("=" * 70); print("\n⚙️  CONFIGURATION"); print("-" * 40)
    
    # Balance mode selection
    print("\nBalance Check Mode:"); print("1. NONE (Fastest)"); print("2. QUICK"); print("3. VERIFIED")
    mode_choice = input("\nSelect mode (1-3, default=2): ").strip()
    
    if mode_choice == '1': balance_mode = "none"; check_balance = False
    elif mode_choice == '3': balance_mode = "verified"; check_balance = True
    else: balance_mode = "quick"; check_balance = True
    
    # I/O Configuration
    if check_balance:
        try:
            timeout_input = input(f"\nRequest timeout (seconds, default={request_timeout}): ").strip()
            if timeout_input: request_timeout = int(timeout_input)
            retries_input = input(f"Max retries per check (default={max_retries}): ").strip()
            if retries_input: max_retries = int(retries_input)
        except ValueError: print("Using default I/O values")

        # Proxy Configuration
        print("\n🌐 PROXY CONFIGURATION (Optional)")
        proxy_choice = input("Use Proxy (y/n, default=n)? ").strip().lower()
        if proxy_choice == 'y':
            global USE_PROXY, PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS
            USE_PROXY = True
            PROXY_HOST = input("Proxy Host: ").strip()
            PROXY_PORT = input("Proxy Port: ").strip()
            PROXY_USER = input("Proxy Username (Optional): ").strip()
            PROXY_PASS = input("Proxy Password (Optional): ").strip()
            setup_proxy()
            if _PROXIES: print(f"✅ Proxy configured.")
            else: print("❌ Proxy configuration failed. Using direct connection."); USE_PROXY = False
            
        # Telegram Confirmation
        print("\n📢 TELEGRAM NOTIFICATION")
        tg_confirm = input(f"Send alert to Telegram (Chat ID {TELEGRAM_CHAT_ID}) on non-zero balance? (y/n, default=y): ").strip().lower()
        if tg_confirm == 'n':
            USE_TELEGRAM = False
        else:
            USE_TELEGRAM = True
            print("✅ Telegram notification active.")
    
    # Prefix length
    try:
        input_len = input("\nEnter Prefix Length (1-34, default=5): ").strip()
        min_match_length = int(input_len) if input_len else 5
        if not (1 <= min_match_length <= 34): min_match_length = 5
    except ValueError: min_match_length = 5
    
    # Check target file
    target_file = "P2PKH_All.txt"
    if not os.path.exists(target_file):
        print(f"\n❌ Error: {target_file} not found!"); print(f"Please create {target_file} with target addresses."); return
    
    target_data = load_target_addresses(target_file, min_match_length)
    if not target_data: return
    
    initialize_found_file(min_match_length, balance_mode)
    
    print(f"\n✅ Successfully loaded targets")
    print(f"📊 Unique prefixes: {len(target_data['compressed'])}")
    print(f"💻 CPU Processes: {NUM_PROCESSES}/{TOTAL_CORES}")
    print(f"⚖️  Balance mode: {balance_mode.upper()}")
    
    print("-" * 70)
    
    confirm = input(f"\nStart search with {min_match_length}-character prefix? (y/n): ")
    if confirm.lower() == 'y':
        matches = find_multi_vanity_address(target_data, min_match_length)
        print(f"\n✅ Session completed!"); print(f"📊 Matches found in session: {matches}")
    else:
        print("Search cancelled.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
