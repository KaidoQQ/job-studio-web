@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m job_studio.server
) else (
  python -m job_studio.server
)
