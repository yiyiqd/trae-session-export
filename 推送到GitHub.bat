@echo off
cd /d "%~dp0"
title 推送到 GitHub
set GIT=..\tools\PortableGit\bin\git.exe
if not exist "%GIT%" set GIT=C:\Program Files\Git\bin\git.exe
if not exist "%GIT%" (
  echo 没找到 git，请确认 tools\PortableGit 目录存在
  pause
  exit /b
)

echo [1/3] 收集本次改动...
"%GIT%" add -A
"%GIT%" commit -m "update" >nul 2>&1

echo.
set /p GH_USER=请输入你的 GitHub 用户名后回车: 
if "%GH_USER%"=="" (
  echo 用户名不能为空
  pause
  exit /b
)

"%GIT%" remote remove origin >nul 2>&1
"%GIT%" remote add origin https://github.com/%GH_USER%/trae-session-export.git

echo.
echo [2/3] 推送中... 如果弹出浏览器，请登录 GitHub 并点绿色的授权按钮
echo.
"%GIT%" push -u origin main
echo.
echo [3/3] 完成！去网页刷新看看你的仓库吧。
pause
