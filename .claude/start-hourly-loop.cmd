@echo off
schtasks.exe /Delete /TN "ClaudeCode-TaiwanMoneyflow-Loop-Bootstrap" /F >nul 2>&1
cd /d C:\Workspace_CN\taiwan_moneyflow_rotation
"C:\Users\tommy\.local\bin\claude.exe" --permission-mode auto --name "Taiwan-Moneyflow-Hourly" "/loop 1h Work only inside C:\Workspace_CN\taiwan_moneyflow_rotation. On every wake, read and obey .claude\loop.md, then resume from loop\PROJECT_STATE.md. Never commit, push, delete material data, modify anything outside this project, weaken tests, or advance a checkpoint after quota/auth/tool failure."
