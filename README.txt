Requires Python 3.11+, Redis, and a .env file with TABSCANNER_API_KEY and OPENAI_API_KEY.

T1: redis-server.exe (this one in location of redis file)
T2: 
.\venv\Scripts\Activate.ps1
python worker.py
T3:
.\venv\Scripts\Activate.ps1
flask --app app run


http://127.0.0.1:5000
