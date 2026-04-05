@echo off
REM Engram auto-tagging batch script
REM Schedule via Windows Task Scheduler to run periodically.
REM
REM Example (run twice daily at 10:30 and 00:00):
REM   schtasks /create /tn "Engram Tag Morning" /tr "%~dp0engram-tag.bat" /sc daily /st 10:30
REM   schtasks /create /tn "Engram Tag Night"   /tr "%~dp0engram-tag.bat" /sc daily /st 00:00
REM
REM Linux/macOS cron equivalent:
REM   30 10 * * * engram tag --provider both --batch-size 200
REM   0  0  * * * engram tag --provider both --batch-size 200

REM Run keyword tagging first (instant, no external calls)
engram tag --provider keyword --batch-size 200

REM Then CLI tagging (uses claude/codex CLI, account-based)
engram tag --provider cli --batch-size 50
