@echo off
chcp 65001 >nul
title ComfyUI Deps - Web GUI

echo ============================================
echo   ComfyUI 插件依赖管理器
echo ============================================
echo.

comfyui-deps --help >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未安装 comfyui-deps，请先运行 install.bat
    echo 或执行: pip install . --break-system-packages
    pause
    exit /b 1
)

echo [信息] 启动 Web GUI...
echo.

comfyui-deps

pause
