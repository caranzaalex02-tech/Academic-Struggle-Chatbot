@echo off
cd /d %~dp0
echo Starting Mental Health Chatbot...
start http://127.0.0.1:5000
py app.py
pause
