@echo off
REM Engram auto-tagging batch script
REM Schedule via Windows Task Scheduler: 10:30 and 00:00 daily
REM
REM schtasks usage:
REM   schtasks /create /tn "Engram Tag Morning" /tr "E:\Dropbox\obsidian\obsidian-engram\scripts\engram-tag.bat" /sc daily /st 10:30
REM   schtasks /create /tn "Engram Tag Night"   /tr "E:\Dropbox\obsidian\obsidian-engram\scripts\engram-tag.bat" /sc daily /st 00:00

set ENGRAM_DIR=E:\Dropbox\obsidian
cd /d "%ENGRAM_DIR%"

REM Run keyword tagging first (instant, no external calls)
engram tag --provider keyword --batch-size 200

REM Then CLI tagging (uses claude -p, account-based)
engram tag --provider cli --batch-size 50

echo [%date% %time%] Tagging complete >> "%ENGRAM_DIR%\.engram\tag.log"
