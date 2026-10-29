@echo off
rem Opens the GradScout home window.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" app\gui.py
