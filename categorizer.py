import os
import sqlite3
import json
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from openai import OpenAI
from receipt_scanner import scan_receipt, parse_line_items
import npl

load_dotenv()
DB_FILE = 'items.db'

CATEGORIES_LIST = "Groceries, Housing, Household, Clothing, Electronics, Transport, Health, Entertainment, Restaurant, Takeout, Utilities, Subscriptions, Insurance, Other"

INR_TO_GBP = 0.0094

CATEGORY_MAPPING = {
    'Housing': 'Rent',
    'Restaurant': 'Eating_Out',
    'Takeout': 'Eating_Out',
    'Health': 'Healthcare',
    'Groceries': 'Groceries',
    'Transport': 'Transport',
    'Entertainment': 'Entertainment',
    'Utilities': 'Utilities',
    'Education': 'Education',
    'Insurance': 'Insurance',
    'Other': 'Miscellaneous',
    'Household': 'Miscellaneous',
    'Clothing': 'Miscellaneous',
    'Electronics': 'Miscellaneous',
    'Subscriptions': 'Miscellaneous'
}

CATEGORY_ORDER = [
    'Housing', 'Utilities', 'Groceries', 'Transport', 'Insurance',
    'Health', 'Restaurant', 'Takeout', 'Entertainment', 'Subscriptions',
    'Household', 'Clothing', 'Electronics', 'Education', 'Other'
]

INCOME_BRACKETS = [
    {'label': 'Under £15k/year', 'min': 0, 'max': 1250},
    {'label': '£15k - £25k/year', 'min': 1250, 'max': 2083},
    {'label': '£25k - £35k/year', 'min': 2083, 'max': 2917},
    {'label': '£35k - £50k/year', 'min': 2917, 'max': 4167},
    {'label': '£50k - £75k/year', 'min': 4167, 'max': 6250},
    {'label': 'Over £75k/year', 'min': 6250, 'max': float('inf')}
]

DISCRETIONARY_CATEGORIES = {'Restaurant', 'Takeout', 'Entertainment', 'Clothing', 'Electronics', 'Subscriptions'}

MIN_ABSOLUTE_CHANGE = 15.0


def get_income_bracket_label(monthly_income):
    for bracket in INCOME_BRACKETS:
        if bracket['min'] <= monthly_income < bracket['max']:
            return bracket['label']
    return INCOME_BRACKETS[-1]['label']


def init_db():
    os.makedirs('receipts', exist_ok=True)
    with sqlite3.connect(DB_FILE) as con:
        con.execute("PRAGMA journal_mode=WAL")
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                savings_balance REAL DEFAULT 0,
                goal_amount REAL DEFAULT NULL,
                goal_date TEXT DEFAULT NULL
            )
        """)
        for col, definition in [
            ('savings_balance', 'REAL DEFAULT 0'),
            ('goal_amount',     'REAL DEFAULT NULL'),
            ('goal_date',       'TEXT DEFAULT NULL'),
        ]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass

        cur.execute("CREATE TABLE IF NOT EXISTS raw_item_cache (raw_name TEXT PRIMARY KEY, root_item TEXT NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS root_item_categories (root_item TEXT PRIMARY KEY, category TEXT NOT NULL)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS spending_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                cost REAL NOT NULL,
                category TEXT NOT NULL,
                receipt_name TEXT,
                date_added TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS income_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                amount REAL NOT NULL,
                date_added TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS temp_receipts (
                job_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                items_json TEXT,
                receipt_date TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recurring_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT,
                type TEXT NOT NULL,
                frequency TEXT NOT NULL,
                start_date TEXT NOT NULL,
                next_due_date TEXT NOT NULL,
                end_date TEXT,
                active BOOLEAN DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS category_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                monthly_limit REAL NOT NULL,
                UNIQUE(user_id, category),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        con.commit()


try:
    client = OpenAI()
except Exception:
    client = None


def get_category_from_openai(root_item: str) -> str:
    if not client:
        return "Other"
    try:
        prompt = f"Categorize '{root_item}' into one of: {CATEGORIES_LIST}. Respond with ONLY the category name."
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        cat = completion.choices[0].message.content.strip()
        return cat if cat in CATEGORIES_LIST else "Other"
    except Exception:
        return "Other"


def get_item_info(raw_item_name: str, con: sqlite3.Connection) -> tuple:
    raw_name = raw_item_name.upper().strip()
    cur = con.cursor()
    cur.execute("SELECT root_item FROM raw_item_cache WHERE raw_name = ?", (raw_name,))
    result = cur.fetchone()
    root_item = result[0] if result else npl.basic_clean(raw_name).upper()
    cur.execute("SELECT category FROM root_item_categories WHERE root_item = ?", (root_item,))
    cat_result = cur.fetchone()
    category = cat_result[0] if cat_result else get_category_from_openai(root_item)
    return category, root_item


def update_caches_from_correction(corrected_item: dict, original_raw_name: str, con: sqlite3.Connection):
    cur = con.cursor()
    raw_name_key = original_raw_name.upper().strip()
    final_root_item = corrected_item['Item'].upper().strip()
    new_category = corrected_item['Category'].strip()
    nlp_guess = npl.basic_clean(raw_name_key).upper()
    if nlp_guess != final_root_item:
        cur.execute("INSERT OR REPLACE INTO raw_item_cache (raw_name, root_item) VALUES (?, ?)", (raw_name_key, final_root_item))
    cur.execute("INSERT OR REPLACE INTO root_item_categories (root_item, category) VALUES (?, ?)", (final_root_item, new_category))


def log_spending(categorized_items: list, receipt_name: str, receipt_date: str, user_id: int, con: sqlite3.Connection):
    entries = []
    for item in categorized_items:
        try:
            cost = float(item['Cost'])
            entries.append((user_id, item['Item'], cost, item['Category'], receipt_name, receipt_date))
        except ValueError:
            pass
    if not entries:
        return
    cur = con.cursor()
    cur.executemany(
        "INSERT INTO spending_log (user_id, item_name, cost, category, receipt_name, date_added) VALUES (?, ?, ?, ?, ?, ?)",
        entries
    )


def add_manual_transaction(name, amount, category, date_str, trans_type, is_recurring, frequency, end_date, user_id, con):
    cur = con.cursor()
    if is_recurring:
        cur.execute("""
            INSERT INTO recurring_templates (user_id, name, amount, category, type, frequency, start_date, next_due_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, name, amount, category, trans_type, frequency, date_str, date_str, end_date))
        generate_recurring_transactions(user_id, con)
    else:
        if trans_type == 'income':
            cur.execute(
                "INSERT INTO income_log (user_id, source_name, amount, date_added) VALUES (?, ?, ?, ?)",
                (user_id, name, amount, date_str)
            )
        else:
            cur.execute(
                "INSERT INTO spending_log (user_id, item_name, cost, category, receipt_name, date_added) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, name, amount, category, "Manual Entry", date_str)
            )


def generate_recurring_transactions(user_id: int, con):
    cur = con.cursor()
    today = datetime.now().date()
    cur.execute("SELECT * FROM recurring_templates WHERE active = 1 AND user_id = ?", (user_id,))
    templates = cur.fetchall()

    for t in templates:
        t_id = t[0]
        name = t[2]
        amount = t[3]
        category = t[4]
        trans_type = t[5]
        frequency = t[6]
        next_due_str = t[8]
        end_date_str = t[9]

        try:
            next_due = datetime.strptime(next_due_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        except ValueError:
            continue

        while next_due <= today:
            if end_date and next_due > end_date:
                cur.execute("UPDATE recurring_templates SET active = 0 WHERE id = ?", (t_id,))
                break

            if trans_type == 'income':
                cur.execute(
                    "INSERT INTO income_log (user_id, source_name, amount, date_added) VALUES (?, ?, ?, ?)",
                    (user_id, name, amount, next_due.strftime('%Y-%m-%d'))
                )
            else:
                cur.execute(
                    "INSERT INTO spending_log (user_id, item_name, cost, category, receipt_name, date_added) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, name, amount, category, "Recurring", next_due.strftime('%Y-%m-%d'))
                )

            if frequency == 'weekly':
                next_due += timedelta(weeks=1)
            elif frequency == 'biweekly':
                next_due += timedelta(weeks=2)
            elif frequency == 'monthly':
                next_due += relativedelta(months=1)
            elif frequency == 'yearly':
                next_due += relativedelta(years=1)
            else:
                next_due += relativedelta(months=1)

            cur.execute("UPDATE recurring_templates SET next_due_date = ? WHERE id = ?", (next_due.strftime('%Y-%m-%d'), t_id))

    con.commit()


def calculate_monthly_income(user_id: int) -> float:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        cur.execute("""
            SELECT AVG(monthly_total) FROM (
                SELECT strftime('%Y-%m', date_added) as month, SUM(amount) as monthly_total
                FROM income_log
                WHERE user_id = ? AND date_added >= ?
                GROUP BY month
            )
        """, (user_id, six_months_ago))
        result = cur.fetchone()
        return round(result[0], 2) if result[0] else 0.0


def get_current_balance(user_id: int) -> float:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT savings_balance FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        baseline = row[0] if row and row[0] is not None else 0.0

        cur.execute("SELECT COALESCE(SUM(amount), 0) FROM income_log WHERE user_id = ?", (user_id,))
        total_income = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(cost), 0) FROM spending_log WHERE user_id = ?", (user_id,))
        total_expenses = cur.fetchone()[0]

    return round(baseline + total_income - total_expenses, 2)


def get_avg_monthly_savings(user_id: int) -> float:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        three_months_ago = (datetime.now() - relativedelta(months=3)).strftime('%Y-%m-%d')

        cur.execute("""
            SELECT COALESCE(SUM(amount), 0) / 3.0
            FROM income_log
            WHERE user_id = ? AND date_added >= ?
        """, (user_id, three_months_ago))
        avg_income = cur.fetchone()[0]

        cur.execute("""
            SELECT COALESCE(SUM(cost), 0) / 3.0
            FROM spending_log
            WHERE user_id = ? AND date_added >= ?
        """, (user_id, three_months_ago))
        avg_expenses = cur.fetchone()[0]

    return round(avg_income - avg_expenses, 2)


def get_goal_progress(user_id: int, monthly_spending_dict: dict, csv_path: str = 'data__1_.csv') -> dict | None:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT goal_amount, goal_date FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()

    if not row or not row[0] or not row[1]:
        return None

    goal_amount = float(row[0])
    goal_date_str = row[1]

    try:
        goal_date = datetime.strptime(goal_date_str, '%Y-%m-%d').date()
    except ValueError:
        return None

    today = datetime.now().date()
    if goal_date <= today:
        months_remaining = 0
    else:
        delta = relativedelta(goal_date, today)
        months_remaining = delta.years * 12 + delta.months + (1 if delta.days > 0 else 0)

    current_balance   = get_current_balance(user_id)
    avg_savings       = get_avg_monthly_savings(user_id)
    projected_balance = round(current_balance + (avg_savings * months_remaining), 2)
    money_still_needed = goal_amount - current_balance
    monthly_needed    = round(money_still_needed / months_remaining, 2) if months_remaining > 0 else None
    shortfall         = round(goal_amount - projected_balance, 2)
    progress_pct      = min(100, round((current_balance / goal_amount) * 100, 1)) if goal_amount > 0 else 0
    on_track          = projected_balance >= goal_amount

    gap_suggestions = []
    try:
        df = pd.read_csv(csv_path)
        user_income = calculate_monthly_income(user_id)
        if user_income > 0 and not df.empty:
            user_income_inr = user_income / INR_TO_GBP
            peer_df = df[
                (df['Income'] >= user_income_inr * 0.8) &
                (df['Income'] <= user_income_inr * 1.2)
            ]
            if peer_df.empty:
                peer_df = df[
                    (df['Income'] >= user_income_inr * 0.7) &
                    (df['Income'] <= user_income_inr * 1.3)
                ]

            if not peer_df.empty:
                for category, user_amount in monthly_spending_dict.items():
                    if user_amount <= 0:
                        continue
                    csv_cat = CATEGORY_MAPPING.get(category)
                    if not csv_cat or csv_cat not in peer_df.columns:
                        continue
                    peer_amount = round(peer_df[csv_cat].mean() * INR_TO_GBP, 2)
                    overspend = round(user_amount - peer_amount, 2)
                    if overspend >= 10:
                        gap_suggestions.append({
                            'category':    category,
                            'user_amount': round(user_amount, 2),
                            'peer_amount': peer_amount,
                            'overspend':   overspend,
                        })

        gap_suggestions.sort(key=lambda x: -x['overspend'])
        gap_suggestions = gap_suggestions[:4]
    except Exception:
        pass

    return {
        'goal_amount':       goal_amount,
        'goal_date':         goal_date_str,
        'goal_date_display': goal_date.strftime('%d %b %Y'),
        'current_balance':   current_balance,
        'avg_monthly_savings': avg_savings,
        'projected_balance': projected_balance,
        'monthly_needed':    monthly_needed,
        'months_remaining':  months_remaining,
        'shortfall':         shortfall,
        'progress_pct':      progress_pct,
        'on_track':          on_track,
        'gap_suggestions':   gap_suggestions,
    }


def update_user_settings(user_id: int, savings_balance: float = None,
                         goal_amount: float = None, goal_date: str = None,
                         clear_goal: bool = False):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        if savings_balance is not None:
            cur.execute("UPDATE users SET savings_balance = ? WHERE id = ?", (savings_balance, user_id))
        if clear_goal:
            cur.execute("UPDATE users SET goal_amount = NULL, goal_date = NULL WHERE id = ?", (user_id,))
        else:
            if goal_amount is not None:
                cur.execute("UPDATE users SET goal_amount = ? WHERE id = ?", (goal_amount, user_id))
            if goal_date is not None:
                cur.execute("UPDATE users SET goal_date = ? WHERE id = ?", (goal_date, user_id))
        con.commit()


def get_user_settings(user_id: int) -> dict:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT savings_balance, goal_amount, goal_date FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
    return {
        'savings_balance': row[0] if row and row[0] is not None else 0.0,
        'goal_amount':     row[1] if row else None,
        'goal_date':       row[2] if row else None,
    }


def get_peer_insights(user_id: int, monthly_spending_dict: dict, csv_path: str = 'data__1_.csv') -> list:
    insights = []
    try:
        user_income = calculate_monthly_income(user_id)
        if user_income == 0:
            return ["Add some income transactions to see how you compare to peers."]

        bracket_label = get_income_bracket_label(user_income)
        insights.append(f"Compared to peers earning {bracket_label}")

        df = pd.read_csv(csv_path)

        user_income_inr = user_income / INR_TO_GBP
        income_lower = user_income_inr * 0.8
        income_upper = user_income_inr * 1.2
        peer_df = df[(df['Income'] >= income_lower) & (df['Income'] <= income_upper)]

        if peer_df.empty:
            return insights + ["No peer data available for your income range."]

        peer_averages = {}
        for app_cat, csv_cat in CATEGORY_MAPPING.items():
            if csv_cat in peer_df.columns:
                peer_spending_gbp = peer_df[csv_cat].mean() * INR_TO_GBP
                peer_averages[app_cat] = (peer_spending_gbp / user_income) * 100

        for category, amount in monthly_spending_dict.items():
            if amount > 0 and category in peer_averages:
                user_pct = (amount / user_income) * 100
                peer_pct = peer_averages[category]
                diff = user_pct - peer_pct
                if abs(diff) > 2:
                    direction = "higher" if diff > 0 else "lower"
                    insights.append(
                        f"You spend {abs(diff):.1f}% {direction} than peers on {category} "
                        f"({user_pct:.1f}% vs {peer_pct:.1f}% of income)"
                    )

        if len(insights) == 1:
            insights.append("Your spending is well-aligned with peers in your income range")

    except FileNotFoundError:
        insights.append("Peer comparison data not found. Place 'data__1_.csv' in the project folder.")
    except Exception as e:
        insights.append(f"Error generating insights: {str(e)}")

    return insights


def _fmt_month(ym: str) -> str:
    try:
        return datetime.strptime(ym, '%Y-%m').strftime('%B %Y')
    except ValueError:
        return ym


def _sort_categories(categories: list) -> list:
    order_map = {cat: idx for idx, cat in enumerate(CATEGORY_ORDER)}
    return sorted(categories, key=lambda c: (order_map.get(c['name'], 999), c['name']))


def get_monthly_overviews(user_id: int) -> list:
    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            SELECT strftime('%Y-%m', date_added) as month, category, SUM(cost) as val
            FROM spending_log WHERE user_id = ? GROUP BY month, category
        """, (user_id,))
        expenses = cur.fetchall()
        cur.execute("""
            SELECT strftime('%Y-%m', date_added) as month, SUM(amount) as val
            FROM income_log WHERE user_id = ? GROUP BY month
        """, (user_id,))
        income = cur.fetchall()

    data = {}

    def ensure_month(m):
        if m not in data:
            data[m] = {'income': 0, 'expense': 0, 'categories': [], 'profit': 0}

    for row in expenses:
        m = row['month']
        ensure_month(m)
        data[m]['expense'] += row['val']
        data[m]['categories'].append({'name': row['category'], 'val': row['val']})

    for row in income:
        m = row['month']
        ensure_month(m)
        data[m]['income'] += row['val']

    for m in data:
        data[m]['profit'] = data[m]['income'] - data[m]['expense']
        data[m]['month_name'] = _fmt_month(m)
        data[m]['month_key'] = m
        data[m]['categories'] = _sort_categories(data[m]['categories'])

    sorted_months = sorted(data.keys(), reverse=True)
    final_list = []

    for i, month in enumerate(sorted_months):
        current = data[month]
        if i + 1 < len(sorted_months):
            prev = data[sorted_months[i + 1]]
            current['diff_income'] = current['income'] - prev['income']
            current['diff_expense'] = current['expense'] - prev['expense']
            current['diff_profit'] = current['profit'] - prev['profit']
        else:
            current['diff_income'] = 0
            current['diff_expense'] = 0
            current['diff_profit'] = 0
        final_list.append(current)

    return final_list


def get_temp_receipt_items(job_id: str) -> dict:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT status, items_json, filename, receipt_date FROM temp_receipts WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        if row:
            status, items_json, filename, receipt_date = row
            if status == 'complete':
                return {'status': 'complete', 'items': json.loads(items_json), 'filename': filename, 'receipt_date': receipt_date}
            return {'status': status}
        return {'status': 'not_found'}


SPENDING_TIPS = {
    'Groceries': 'Meal planning and a fixed shopping list typically cut grocery bills by 20-30%. Own-brand products are usually identical in quality.',
    'Housing': 'If rent exceeds 35% of your take-home pay, it may be worth exploring whether moving or taking in a lodger is viable.',
    'Transport': 'A monthly travel pass is almost always cheaper than pay-as-you-go. If you drive, consolidating trips saves on fuel.',
    'Restaurant': 'Cooking at home an extra 3-4 times a month typically saves £60-90 without meaningfully affecting quality of life.',
    'Takeout': 'Batch cooking one day a week tends to reduce takeaway frequency naturally — it removes the "nothing ready to eat" trigger.',
    'Entertainment': 'Check whether any subscriptions already cover what you are paying for separately (e.g. cinema via a streaming bundle).',
    'Subscriptions': 'Audit all subscriptions every 3 months. Unused ones are easy to forget. Average household can save £30-50/month by cancelling overlap.',
    'Utilities': 'Switching energy provider annually and using a comparison site typically saves £100-200/year. A smart meter helps track usage.',
    'Health': 'NHS services cover most routine needs. For prescriptions, a prepayment certificate (PPC) caps costs at around £30 per quarter.',
    'Clothing': 'End-of-season sales and second-hand platforms (Vinted, eBay) offer significant savings, especially on brands.',
    'Electronics': 'Refurbished devices from manufacturer-certified outlets are typically 30-40% cheaper and carry a warranty.',
    'Other': 'Unspecified spending is worth reviewing — small recurring costs often hide here and add up quickly.'
}


def get_spending_trends(user_id: int) -> list:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()

        today = datetime.now()
        recent_start  = (today - relativedelta(months=3)).strftime('%Y-%m-%d')
        earlier_start = (today - relativedelta(months=6)).strftime('%Y-%m-%d')
        earlier_end   = (today - relativedelta(months=3)).strftime('%Y-%m-%d')

        cur.execute("""
            SELECT category, SUM(cost) / 3.0 as monthly_avg
            FROM spending_log
            WHERE user_id = ? AND date_added >= ?
            GROUP BY category
        """, (user_id, recent_start))
        recent = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute("""
            SELECT category, SUM(cost) / 3.0 as monthly_avg
            FROM spending_log
            WHERE user_id = ? AND date_added >= ? AND date_added < ?
            GROUP BY category
        """, (user_id, earlier_start, earlier_end))
        earlier = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute("""
            SELECT SUM(amount) / 3.0
            FROM income_log
            WHERE user_id = ? AND date_added >= ?
        """, (user_id, recent_start))
        row = cur.fetchone()
        avg_monthly_income = row[0] if row[0] else 0.0

        recent_total_spend = sum(recent.values())
        in_deficit = avg_monthly_income > 0 and recent_total_spend > avg_monthly_income

    trends = []
    all_categories = set(recent.keys()) | set(earlier.keys())

    for category in all_categories:
        recent_avg  = recent.get(category, 0.0)
        earlier_avg = earlier.get(category, 0.0)

        if earlier_avg <= 0:
            continue

        absolute_change = recent_avg - earlier_avg
        change_percent  = (absolute_change / earlier_avg) * 100

        if abs(change_percent) < 15 or abs(absolute_change) < MIN_ABSOLUTE_CHANGE:
            continue

        direction = 'increasing' if absolute_change > 0 else 'decreasing'
        is_discretionary = category in DISCRETIONARY_CATEGORIES
        is_concern = direction == 'increasing' and (not is_discretionary or in_deficit)

        description = (
            f"{category} averaged £{recent_avg:.0f}/month over the last 3 months, "
            f"vs £{earlier_avg:.0f}/month in the 3 months before that "
            f"— a {abs(change_percent):.0f}% {'increase' if direction == 'increasing' else 'decrease'} "
            f"(£{abs(absolute_change):.0f}/month {'more' if direction == 'increasing' else 'less'})."
        )

        tip = SPENDING_TIPS.get(category, '') if is_concern else ''

        trends.append({
            'category':        category,
            'direction':       direction,
            'change_percent':  abs(change_percent),
            'old_amount':      earlier_avg,
            'new_amount':      recent_avg,
            'absolute_change': abs(absolute_change),
            'is_concern':      is_concern,
            'description':     description,
            'tip':             tip,
        })

    trends.sort(key=lambda x: (not x['is_concern'], -x['absolute_change']))
    return trends[:6]


def get_insights_with_tips(user_id: int, monthly_spending_dict: dict, csv_path: str = 'data__1_.csv',
                           match_cats: list = None, match_income: bool = True) -> list:
    insights = []

    try:
        user_income = calculate_monthly_income(user_id)

        if user_income == 0:
            return ["Add some income entries to see peer comparisons."]

        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            return ["Peer comparison data file not found."]

        required_cols = ['Income', 'Rent', 'Groceries', 'Transport', 'Eating_Out',
                         'Entertainment', 'Utilities', 'Healthcare', 'Education', 'Miscellaneous']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return ["Peer comparison data is missing required columns."]

        user_income_inr = user_income / INR_TO_GBP
        peer_df = df.copy()

        if match_income:
            peer_df = peer_df[(peer_df['Income'] >= user_income_inr * 0.8) & (peer_df['Income'] <= user_income_inr * 1.2)]
            if peer_df.empty:
                peer_df = df[(df['Income'] >= user_income_inr * 0.7) & (df['Income'] <= user_income_inr * 1.3)]
                if peer_df.empty:
                    return ["No peer data available for your income range."]

        if match_cats:
            for cat in match_cats:
                csv_cat = CATEGORY_MAPPING.get(cat)
                if not csv_cat or csv_cat not in peer_df.columns:
                    continue
                user_spend_inr = monthly_spending_dict.get(cat, 0) / INR_TO_GBP
                if user_spend_inr <= 0:
                    continue
                peer_df = peer_df[
                    (peer_df[csv_cat] >= user_spend_inr * 0.75) &
                    (peer_df[csv_cat] <= user_spend_inr * 1.25)
                ]
            if peer_df.empty:
                return ["No peers found matching your selected categories. Try fewer filters."]

        peer_count = len(peer_df)

        peer_averages = {}
        for app_cat, csv_cat in CATEGORY_MAPPING.items():
            if csv_cat in peer_df.columns:
                peer_gbp = peer_df[csv_cat].mean() * INR_TO_GBP
                peer_averages[app_cat] = {
                    'percentage': (peer_gbp / user_income) * 100,
                    'amount_gbp': peer_gbp
                }

        aggregated = {}
        for category, amount in monthly_spending_dict.items():
            aggregated[category] = aggregated.get(category, 0) + amount

        total_user_spend = sum(aggregated.values())
        savings_rate = (user_income - total_user_spend) / user_income if user_income > 0 else 0
        in_deficit = total_user_spend > user_income

        higher_items = []
        lower_items  = []

        for category, user_amount in aggregated.items():
            if user_amount <= 0 or category not in peer_averages:
                continue

            user_pct  = (user_amount / user_income) * 100
            peer_data = peer_averages[category]
            peer_pct  = peer_data['percentage']
            diff      = user_pct - peer_pct

            if abs(diff) < 2 or abs(user_amount - peer_data['amount_gbp']) < 10:
                continue

            is_discretionary = category in DISCRETIONARY_CATEGORIES

            if diff > 0:
                is_concern = not is_discretionary or in_deficit or savings_rate < 0.10
                higher_items.append({
                    'category':         category,
                    'user_pct':         user_pct,
                    'peer_pct':         peer_pct,
                    'diff':             diff,
                    'user_amount':      user_amount,
                    'peer_amount':      peer_data['amount_gbp'],
                    'is_concern':       is_concern,
                    'is_discretionary': is_discretionary,
                })
            else:
                lower_items.append({
                    'category':    category,
                    'user_pct':    user_pct,
                    'peer_pct':    peer_pct,
                    'diff':        diff,
                    'user_amount': user_amount,
                    'peer_amount': peer_data['amount_gbp'],
                })

        higher_items.sort(key=lambda x: (not x['is_concern'], -x['diff']))

        if not higher_items and not lower_items:
            insights.append(
                f"Based on {peer_count:,} people with similar income: "
                f"your spending is well-aligned with peers across all categories."
            )
            return insights

        if match_cats:
            cat_labels = ' + '.join(match_cats)
            income_part = ' and similar income' if match_income else ''
            insights.append(f"Based on {peer_count:,} people with similar {cat_labels} spend{income_part}:")
        else:
            insights.append(f"Based on {peer_count:,} people with similar income ({get_income_bracket_label(user_income)}):") 

        for item in higher_items:
            category    = item['category']
            diff        = item['diff']
            user_amount = item['user_amount']
            peer_amount = item['peer_amount']
            is_concern  = item['is_concern']

            if is_concern:
                line = (
                    f"Your {category} spend is {diff:.1f}% above the peer average "
                    f"(£{user_amount:.0f} vs £{peer_amount:.0f}/month). "
                    f"This is eating into your budget."
                )
                tip = SPENDING_TIPS.get(category, '')
                if tip:
                    line += f" {tip}"
            else:
                line = (
                    f"Your {category} spend is above average for your income bracket "
                    f"(£{user_amount:.0f} vs £{peer_amount:.0f}/month), but your overall "
                    f"savings rate is healthy so this is not a concern."
                )
            insights.append(line)

        for item in lower_items[:3]:
            category    = item['category']
            diff        = abs(item['diff'])
            user_amount = item['user_amount']
            peer_amount = item['peer_amount']
            insights.append(
                f"Your {category} spend is {diff:.1f}% below the peer average "
                f"(£{user_amount:.0f} vs £{peer_amount:.0f}/month) — you are keeping this well under control."
            )

    except Exception as e:
        insights.append(f"Error generating insights: {str(e)}")

    return insights


def process_receipt_job(job_id: str, image_path: str, receipt_filename: str):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        try:
            cur.execute("INSERT INTO temp_receipts (job_id, filename, status) VALUES (?, ?, ?)", (job_id, receipt_filename, 'pending'))
            con.commit()
        except Exception:
            pass
        try:
            raw_json_result = scan_receipt(image_path)
            receipt_date = raw_json_result.get('dateISO', datetime.now().strftime('%Y-%m-%d'))
            items, _ = parse_line_items(raw_json_result)
            categorized_items = []
            for item in items:
                cat, root = get_item_info(item['Item'], con)
                categorized_items.append({'Raw_OCR': item['Item'], 'Item': root, 'Cost': item['Cost'], 'Category': cat})
            items_json = json.dumps(categorized_items)
            cur.execute(
                "UPDATE temp_receipts SET status=?, items_json=?, receipt_date=? WHERE job_id=?",
                ('complete', items_json, receipt_date, job_id)
            )
            con.commit()
        except Exception:
            cur.execute("UPDATE temp_receipts SET status='error' WHERE job_id=?", (job_id,))
            con.commit()


def get_item_alerts(user_id: int) -> list:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()

        today = datetime.now()
        this_month_start = today.replace(day=1).strftime('%Y-%m-%d')
        last_month_start = (today.replace(day=1) - relativedelta(months=1)).strftime('%Y-%m-%d')

        cur.execute("""
            SELECT item_name, COUNT(*) as times_bought, SUM(cost) as total_spent
            FROM spending_log
            WHERE user_id = ? AND date_added >= ?
            GROUP BY item_name
            HAVING COUNT(*) > 1 AND SUM(cost) >= 10
            ORDER BY total_spent DESC
        """, (user_id, this_month_start))
        this_month = {row[0]: {'count': row[1], 'total': row[2]} for row in cur.fetchall()}

        cur.execute("""
            SELECT item_name, COUNT(*) as times_bought, SUM(cost) as total_spent
            FROM spending_log
            WHERE user_id = ? AND date_added >= ? AND date_added < ?
            GROUP BY item_name
            HAVING COUNT(*) > 1
        """, (user_id, last_month_start, this_month_start))
        last_month = {row[0]: {'count': row[1], 'total': row[2]} for row in cur.fetchall()}

    alerts = []

    for item_name, this in this_month.items():
        last = last_month.get(item_name)

        if last is None:
            alerts.append({
                'item': item_name,
                'this_count': this['count'],
                'this_total': round(this['total'], 2),
                'last_total': 0,
                'change': round(this['total'], 2),
                'is_new': True,
            })
        else:
            change = this['total'] - last['total']
            if change >= 10:
                alerts.append({
                    'item': item_name,
                    'this_count': this['count'],
                    'this_total': round(this['total'], 2),
                    'last_total': round(last['total'], 2),
                    'change': round(change, 2),
                    'is_new': False,
                })

    alerts.sort(key=lambda x: -x['change'])
    return alerts[:6]


def get_category_budgets(user_id: int) -> list:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT id, category, monthly_limit FROM category_budgets WHERE user_id = ? ORDER BY category",
            (user_id,)
        )
        return [{'id': r[0], 'category': r[1], 'monthly_limit': r[2]} for r in cur.fetchall()]


def set_category_budget(user_id: int, category: str, monthly_limit: float):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO category_budgets (user_id, category, monthly_limit)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit
        """, (user_id, category, monthly_limit))
        con.commit()


def delete_category_budget(user_id: int, budget_id: int):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute(
            "DELETE FROM category_budgets WHERE id = ? AND user_id = ?",
            (budget_id, user_id)
        )
        con.commit()

def get_ml_predictions(user_id: int) -> dict:
    from sklearn.linear_model import LinearRegression
    import numpy as np

    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT strftime('%Y-%m', date_added) as month, category, SUM(cost) as total
            FROM spending_log
            WHERE user_id = ?
            GROUP BY month, category
            ORDER BY month ASC
        """, (user_id,))
        rows = cur.fetchall()

    if not rows:
        return {'predictions': [], 'mae': None, 'baseline_mae': None}

    from collections import defaultdict
    monthly = defaultdict(dict)
    for month, category, total in rows:
        monthly[month][category] = total

    months_sorted = sorted(monthly.keys())
    all_categories = set()
    for m in months_sorted:
        all_categories.update(monthly[m].keys())

    predictions = []
    all_errors = []
    all_baseline_errors = []

    for cat in all_categories:
        series = [monthly[m].get(cat, 0) for m in months_sorted]

        if len(series) < 3:
            continue

        X = np.array(range(len(series))).reshape(-1, 1)
        y = np.array(series)

        if len(series) >= 4:
            X_train = X[:-1]
            y_train = y[:-1]
            X_test = X[-1:]
            y_test = y[-1]

            model_eval = LinearRegression()
            model_eval.fit(X_train, y_train)
            pred_test = model_eval.predict(X_test)[0]
            pred_test = max(0, pred_test)

            all_errors.append(abs(pred_test - y_test))
            baseline = np.mean(y_train[-3:])
            all_baseline_errors.append(abs(baseline - y_test))

        model = LinearRegression()
        model.fit(X, y)
        next_x = np.array([[len(series)]])
        predicted = model.predict(next_x)[0]
        predicted = max(0, round(predicted, 2))

        rolling_avg = round(float(np.mean(series[-3:])), 2)

        predictions.append({
            'category': cat,
            'predicted': predicted,
            'rolling_avg': rolling_avg,
            'months_of_data': len(series)
        })

    predictions.sort(key=lambda x: -x['predicted'])

    mae = round(float(np.mean(all_errors)), 2) if all_errors else None
    baseline_mae = round(float(np.mean(all_baseline_errors)), 2) if all_baseline_errors else None

    return {
        'predictions': predictions,
        'mae': mae,
        'baseline_mae': baseline_mae
    }


def search_transactions(user_id: int, query: str = '', category: str = '', month: str = '', include_income: bool = False) -> list:
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        sql = """
            SELECT id, item_name, cost, category, date_added, receipt_name, 'expense' as entry_type
            FROM spending_log
            WHERE user_id = ?
        """
        params = [user_id]
        if query:
            sql += " AND item_name LIKE ?"
            params.append(f'%{query}%')
        if category:
            sql += " AND category = ?"
            params.append(category)
        if month:
            sql += " AND strftime('%Y-%m', date_added) = ?"
            params.append(month)

        if include_income:
            income_sql = """
                UNION ALL
                SELECT id, source_name, amount, 'Income' as category, date_added, NULL, 'income' as entry_type
                FROM income_log
                WHERE user_id = ?
            """
            income_params = [user_id]
            if query:
                income_sql += " AND source_name LIKE ?"
                income_params.append(f'%{query}%')
            if month:
                income_sql += " AND strftime('%Y-%m', date_added) = ?"
                income_params.append(month)
            sql = "SELECT * FROM (" + sql + income_sql + ") ORDER BY date_added DESC LIMIT 200"
            params = params + income_params
        else:
            sql += " ORDER BY date_added DESC LIMIT 200"

        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {'id': r[0], 'name': r[1], 'cost': r[2], 'category': r[3], 'date': r[4], 'source': r[5], 'entry_type': r[6]}
        for r in rows
    ]