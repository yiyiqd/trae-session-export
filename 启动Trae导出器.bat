@echo off
cd /d "%~dp0"
title Trae Session MD 导出器
echo 正在启动 Trae Session MD 导出器 ...
echo 启动后请在浏览器使用 http://127.0.0.1:5001
echo 关闭此窗口即可停止服务。
echo.
start "" http://127.0.0.1:5001
python -X utf8 trae_web.py
pause
