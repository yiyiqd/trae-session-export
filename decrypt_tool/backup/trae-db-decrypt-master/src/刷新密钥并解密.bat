@echo off
cd /d "%~dp0"
title 刷新 Trae 密钥并解密（SOLO + Trae CN）
echo ============================================================
echo  [1/2] 扫描 Trae 进程内存提取 SQLCipher 密钥
echo ============================================================
python -X utf8 scan_solo.py
echo.
echo ============================================================
echo  [2/2] 解密数据库
echo ============================================================
python -X utf8 decrypt_db.py -k decrypted_key.json -d "%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\database.db" -o database_decrypted.db
echo.
echo 完成！
pause
