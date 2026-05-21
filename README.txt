# CoinComrade

A web-based personal finance system that captures item-level spending data through receipt scanning and uses machine learning to predict future spending per category.

## What it does

- Upload a receipt photo and have individual items automatically extracted, categorised and saved
- NLP pipeline normalises raw OCR text with an OpenAI fallback for categorisation
- User corrections are cached persistently so the system learns over time
- Spending dashboard with monthly breakdowns, budget alerts, savings goals, spending trends and peer comparison
- Recurring transactions that generate automatically on login
- Machine learning predictions for next month's spending per category using linear regression

## Tech Stack

| Component | Technology |
|---|---|
| Web framework | Flask |
| Database | SQLite |
| Background processing | Redis + RQ |
| OCR | Tabscanner API |
| NLP | spaCy |
| AI categorisation fallback | OpenAI API |
| ML predictions | scikit-learn |
| Charts | Chart.js |

## Prerequisites

- Python 3.10+
- Redis server running locally on port 6379
- Tabscanner API key
- OpenAI API key

## Setup

1. Clone the repository

```bash
git clone <repo-url>
cd coincomrade
```

2. Create and activate a virtual environment

```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux
```

3. Install dependencies

```bash
pip install flask flask-login werkzeug rq redis spacy openai scikit-learn pandas python-dateutil
python -m spacy download en_core_web_sm
```

4. Create a `.env` file in the root directory
