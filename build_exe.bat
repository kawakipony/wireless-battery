@echo off
cd /d "%~dp0"
echo 正在使用 PyInstaller 打包为独立 Windows 托盘程序...
python -m PyInstaller --noconsole --onefile --clean --name WirelessBatteryMonitor ^
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module scipy ^
  --exclude-module torch --exclude-module tensorflow ^
  run.py
if %errorlevel% neq 0 (
    echo 打包失败，请检查 Python 与 PyInstaller 环境。
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)
echo.
echo 打包完成！可执行文件位于: %~dp0dist\WirelessBatteryMonitor.exe
if /i not "%~1"=="--no-pause" pause
