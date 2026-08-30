"""
Trae CN database.db 解密器
基于 wechat-decrypt 的页面级解密方法
SQLCipher 4: AES-256-CBC, HMAC-SHA512, reserve=80, page_size=4096

用法:
  python src/decrypt_db.py                        # 使用默认路径
  python src/decrypt_db.py -k decrypted_key.json  # 指定密钥文件
"""
import argparse
import hashlib, hmac as hmac_mod, struct, os, sys, json, sqlite3
from Crypto.Cipher import AES

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80
SQLITE_HDR = b'SQLite format 3\x00'

# 默认路径（可通过命令行参数覆盖）
DEFAULT_DB_SRC = "C:/Users/86150/AppData/Roaming/Trae CN/ModularData/ai-agent/database.db"
DEFAULT_KEY_FILE = "decrypted_key.json"
DEFAULT_OUT_DB = "database_decrypted.db"


def derive_mac_key(enc_key, salt):
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)


def decrypt_page(enc_key, page_data, pgno):
    iv = page_data[PAGE_SZ - RESERVE_SZ : PAGE_SZ - RESERVE_SZ + IV_SZ]
    if pgno == 1:
        encrypted = page_data[SALT_SZ : PAGE_SZ - RESERVE_SZ]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        return bytes(bytearray(SQLITE_HDR + decrypted + b'\x00' * RESERVE_SZ))
    else:
        encrypted = page_data[:PAGE_SZ - RESERVE_SZ]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        return decrypted + b'\x00' * RESERVE_SZ


def main():
    parser = argparse.ArgumentParser(description="Trae CN database.db 解密器")
    parser.add_argument("-k", "--key-file", default=DEFAULT_KEY_FILE, help="密钥文件路径")
    parser.add_argument("-d", "--db-path", default=DEFAULT_DB_SRC, help="加密数据库路径")
    parser.add_argument("-o", "--output", default=DEFAULT_OUT_DB, help="输出解密数据库路径")
    args = parser.parse_args()

    with open(args.key_file) as f:
        key_data = json.load(f)

    enc_key = bytes.fromhex(key_data["enc_key"])
    print(f"密钥: {key_data['enc_key'][:16]}...")
    print(f"源数据库: {args.db_path} ({os.path.getsize(args.db_path)/1024/1024:.1f}MB)")

    with open(args.db_path, 'rb') as f:
        page1 = f.read(PAGE_SZ)

    salt = page1[:SALT_SZ]
    print(f"Salt: {salt.hex()}")

    # HMAC 验证
    mac_key = derive_mac_key(enc_key, salt)
    p1_hmac_data = page1[SALT_SZ : PAGE_SZ - RESERVE_SZ + IV_SZ]
    p1_stored_hmac = page1[PAGE_SZ - HMAC_SZ : PAGE_SZ]
    hm = hmac_mod.new(mac_key, p1_hmac_data, hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    if hm.digest() != p1_stored_hmac:
        print("HMAC 验证失败!")
        sys.exit(1)
    print("HMAC 验证通过!")

    # 解密全部页面
    file_size = os.path.getsize(args.db_path)
    total_pages = file_size // PAGE_SZ
    print(f"共 {total_pages} 页，开始解密...")

    with open(args.db_path, 'rb') as fin, open(args.output, 'wb') as fout:
        for pgno in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                page = page + b'\x00' * (PAGE_SZ - len(page))
            fout.write(decrypt_page(enc_key, page, pgno))
            if pgno % 10000 == 0:
                print(f"  进度: {pgno}/{total_pages} ({100*pgno/total_pages:.1f}%)")

    print(f"解密完成: {args.output}")

    # 验证
    conn = sqlite3.connect(args.output)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"表数量: {len(tables)}")
    for t in tables:
        count = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        print(f"  {t}: {count} 行")
    conn.close()


if __name__ == '__main__':
    main()
