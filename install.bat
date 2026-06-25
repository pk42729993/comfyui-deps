@echo off
chcp 65001 >nul
title ComfyUI Deps - 安装

echo ============================================
echo   ComfyUI 插件依赖管理器 - 安装脚本
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

echo [信息] Python 版本:
python --version
echo.

echo [信息] 正在安装 comfyui-deps...
pip install . --break-system-packages
if %errorlevel% neq 0 (
    echo.
    echo [错误] 安装失败，请检查错误信息。
    pause
    exit /b 1
)

echo.
echo [成功] comfyui-deps 安装完成！
echo.
echo 使用方法:
echo   comfyui-deps              启动 Web GUI
echo   comfyui-deps --help       查看所有命令
echo.
pause
