import os
import uuid
import hashlib
import coincurve
import requests
import multiprocessing
import time
import sys
from pybloom_live import ScalableBloomFilter

# --- KONFIGURASI WORKER ---
SERVER_URL = "http://157.245.194.118:8000"
#WORKER_ID = os.uname()[1]  # Nama VPS lu
WORKER_ID = f"{os.uname()[1]}-{str(uuid.uuid4())[:4]}" # Bikin ID unik
MASTER_BF_FILE = "master.bf"

# Load Master Filter ke RAM
print(f"[*] Loading {MASTER_BF_FILE}...")
try:
    with open(MASTER_BF_FILE, "rb") as f:
        MASTER_BF = ScalableBloomFilter.fromfile(f)
    print("[*] Bloom Filter loaded successfully.")
except Exception as e:
    print(f"[!] Error load master.bf: {e}")
    sys.exit(1)

def worker_loop(counter):
    ctx = coincurve.context.Context()
    # Seed unik per worker biar gak tabrakan antar proses
    seed_val = int.from_bytes(os.urandom(32), 'big') + multiprocessing.current_process().pid
    
    while True:
        seed_val += 1
        priv_bytes = seed_val.to_bytes(32, 'big')
        
        # 1. Generate Public Key
        pub = coincurve.PublicKey.from_secret(priv_bytes, ctx)
        pub_compressed = pub.format(compressed=True)
        
        # 2. Ambil Hash160 (Bahan untuk alamat 1, 3, dan bc1q)
        # Sebagian besar 31jt address lu bakal match lewat sini
        h160 = hashlib.new('ripemd160', hashlib.sha256(pub_compressed).digest()).digest()
        h160_hex = h160.hex()

        # 3. Ambil X-Only Pubkey (Khusus Taproot bc1p)
        x_only = pub_compressed[1:].hex()

        # 4. Cek ke Master Filter
        # Kita cek Hash160 OR X-Only
        if h160_hex in MASTER_BF or x_only in MASTER_BF:
            # Match ditemukan! Lapor ke server pusat
            try:
                requests.post(f"{SERVER_URL}/found", json={
                    "priv": priv_bytes.hex(),
                    "type": "Database Match (Binary)",
                    "addr": "N/A - Checking on Server",
                    "bal": "Unknown"
                }, timeout=5)
            except:
                pass

        counter.value += 1

def reporter(counter):
    while True:
        time.sleep(30)
        speed = counter.value / 30
        try:
            # Kirim heartbeat ke server pusat
            requests.post(f"{SERVER_URL}/heartbeat", json={
                "id": WORKER_ID, 
                "speed": int(speed)
            }, timeout=5)
            print(f"[*] Local Speed: {int(speed):,.0f} keys/s | Reported to Server.")
        except:
            pass
        counter.value = 0

if __name__ == "__main__":
    # Gunakan 70% CPU sesuai request lu
    num_cores = multiprocessing.cpu_count()
    use_cores = max(1, int(num_cores * 0.7))
    
    print(f"[*] Worker {WORKER_ID} starting on {use_cores}/{num_cores} cores")
    
    shared_counter = multiprocessing.Value('q', 0)
    
    # Jalankan proses worker
    for _ in range(use_cores):
        p = multiprocessing.Process(target=worker_loop, args=(shared_counter,))
        p.daemon = True
        p.start()
    
    # Jalankan reporter di main thread
    reporter(shared_counter)
