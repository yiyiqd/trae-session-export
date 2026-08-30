@echo off
cd /d "%~dp0"
title 刷新 Trae 密钥并解密（SOLO + Trae CN）
echo ============================================================
echo  [1/3] 扫描 Trae 进程内存提取 SQLCipher 密钥
echo        （需要 TRAE SOLO CN 或 Trae CN 至少一个在运行）
echo ============================================================
python -X utf8 scan_solo.py
echo.
echo ============================================================
echo  [2/3] 解密 TRAE SOLO CN 数据库
echo ============================================================
python -X utf8 decrypt_db.py -k decrypted_key.json -d "%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\database.db" -o database_decrypted.db
echo.
echo ============================================================
echo  [3/3] 解密 Trae CN 数据库
echo        （两程序加密机制相同，本机密钥通用）
echo ============================================================
python -X utf8 decrypt_db.py -k decrypted_key.json -d "%APPDATA%\Trae CN\ModularData\ai-agent\database.db" -o database_traecn_decrypted.db
echo.
echo 完成！回到浏览器刷新（Ctrl+F5）即可看到两个数据源的中文会话标题。
pause
