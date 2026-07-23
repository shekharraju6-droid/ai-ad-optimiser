@echo off
echo Creating scheduled task: Meta Leads Poller every 5 minutes
echo Make sure meta_leads_poller.py and .env are configured correctly.
schtasks /create /tn "Meta Leads Poller" /tr "powershell.exe -ExecutionPolicy Bypass -Command cd '%~dp0'; python meta_leads_poller.py" /sc minute /mo 5 /f
echo.
echo Task created. It will run every 5 minutes.
pause
