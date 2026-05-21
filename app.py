import os
import redis
import sqlite3
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from rq import Queue
from categorizer import (
    init_db, process_receipt_job, get_temp_receipt_items,
    log_spending, update_caches_from_correction, add_manual_transaction,
    generate_recurring_transactions, get_monthly_overviews, calculate_monthly_income,
    get_peer_insights, get_insights_with_tips, get_spending_trends, CATEGORIES_LIST,
    get_goal_progress, update_user_settings, get_user_settings, get_current_balance,
    get_item_alerts, get_category_budgets, set_category_budget, delete_category_budget,
    get_ml_predictions, search_transactions
)

RECEIPTS_FOLDER = "receipts"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
DB_FILE = 'items.db'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = RECEIPTS_FOLDER
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'f7x9kL#2mNp4qRv')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

r = redis.Redis(host='127.0.0.1', port=6379)
q = Queue(connection=r)

with app.app_context():
    init_db()


class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username


@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        if user:
            return User(user[0], user[1])
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        savings_balance = request.form.get('savings_balance', '0') or '0'

        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('signup.html')

        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('signup.html')

        try:
            savings_balance = float(savings_balance)
            if savings_balance < 0:
                savings_balance = 0.0
        except ValueError:
            savings_balance = 0.0

        with sqlite3.connect(DB_FILE) as con:
            cur = con.cursor()
            try:
                hashed_password = generate_password_hash(password)
                cur.execute(
                    "INSERT INTO users (username, password, savings_balance) VALUES (?, ?, ?)",
                    (username, hashed_password, savings_balance)
                )
                con.commit()
                flash('Account created successfully! Please log in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('Username already exists', 'error')
                return render_template('signup.html')

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        with sqlite3.connect(DB_FILE) as con:
            cur = con.cursor()
            cur.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
            user = cur.fetchone()

            if user and check_password_hash(user[2], password):
                login_user(User(user[0], user[1]))
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    with sqlite3.connect(DB_FILE) as con:
        generate_recurring_transactions(current_user.id, con)
    return render_template('index.html')


@app.route('/spending')
@login_required
def spending_page():
    monthly_data = get_monthly_overviews(current_user.id)

    current_month_spending = {}
    if monthly_data:
        for cat_data in monthly_data[0].get('categories', []):
            cat = cat_data['name']
            current_month_spending[cat] = current_month_spending.get(cat, 0) + cat_data['val']

    match_cats = request.args.getlist('match_cat')
    match_income = request.args.get('match_income', '1') == '1'

    insights = get_insights_with_tips(current_user.id, current_month_spending,
                                      match_cats=match_cats if match_cats else None,
                                      match_income=match_income)
    trends = get_spending_trends(current_user.id)
    user_income = calculate_monthly_income(current_user.id)
    goal = get_goal_progress(current_user.id, current_month_spending)
    item_alerts = get_item_alerts(current_user.id)
    budgets = get_category_budgets(current_user.id)
    budget_status = []
    for b in budgets:
        spent = current_month_spending.get(b['category'], 0)
        pct = min(100, round((spent / b['monthly_limit']) * 100, 1)) if b['monthly_limit'] > 0 else 0
        over = pct >= 100
        warning = pct >= 80
        bar_color = '#e53e3e' if over else ('#ed8936' if warning else '#48bb78')
        budget_status.append({
            'id': b['id'],
            'category': b['category'],
            'monthly_limit': b['monthly_limit'],
            'spent': round(spent, 2),
            'remaining': round(max(0, b['monthly_limit'] - spent), 2),
            'pct': pct,
            'warning': warning,
            'over': over,
            'bar_color': bar_color,
        })

    current_month_data = monthly_data[0] if monthly_data else None

    savings_this_month = 0
    if current_month_data:
        savings_this_month = current_month_data['income'] - current_month_data['expense']

    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT category FROM spending_log WHERE user_id = ? ORDER BY category", (current_user.id,))
        spendable_cats = [r[0] for r in cur.fetchall()]

    return render_template('spending.html',
                           months=monthly_data,
                           insights=insights,
                           trends=trends,
                           income=user_income,
                           current_month=current_month_data,
                           savings=savings_this_month,
                           goal=goal,
                           item_alerts=item_alerts,
                           budget_status=budget_status,
                           spendable_cats=spendable_cats,
                           match_cats=match_cats,
                           match_income=match_income)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_balance':
            try:
                new_balance = float(request.form.get('savings_balance', 0))
                update_user_settings(current_user.id, savings_balance=new_balance)
                flash('Savings balance updated.', 'success')
            except ValueError:
                flash('Invalid balance amount.', 'error')

        elif action == 'update_goal':
            try:
                goal_amount = float(request.form.get('goal_amount', 0))
                goal_date = request.form.get('goal_date', '').strip()
                if not goal_date:
                    flash('Please enter a target date.', 'error')
                elif goal_amount <= 0:
                    flash('Goal amount must be greater than zero.', 'error')
                else:
                    update_user_settings(current_user.id, goal_amount=goal_amount, goal_date=goal_date)
                    flash('Savings goal updated.', 'success')
            except ValueError:
                flash('Invalid goal amount.', 'error')

        elif action == 'clear_goal':
            update_user_settings(current_user.id, clear_goal=True)
            flash('Savings goal cleared.', 'success')

        elif action == 'set_budget':
            category = request.form.get('budget_category', '').strip()
            try:
                limit = float(request.form.get('budget_limit', 0))
                if limit <= 0:
                    flash('Budget must be greater than zero.', 'error')
                elif not category:
                    flash('Please select a category.', 'error')
                else:
                    set_category_budget(current_user.id, category, limit)
                    flash(f'Budget for {category} set to £{limit:.2f}/month.', 'success')
            except ValueError:
                flash('Invalid budget amount.', 'error')

        elif action == 'delete_budget':
            try:
                budget_id = int(request.form.get('budget_id', 0))
                delete_category_budget(current_user.id, budget_id)
                flash('Budget removed.', 'success')
            except ValueError:
                flash('Invalid budget.', 'error')

        return redirect(url_for('settings'))

    user_settings = get_user_settings(current_user.id)
    current_balance = get_current_balance(current_user.id)
    budgets = get_category_budgets(current_user.id)
    categories = CATEGORIES_LIST.split(', ')

    from datetime import date
    return render_template('settings.html',
                           user_settings=user_settings,
                           current_balance=current_balance,
                           budgets=budgets,
                           categories=categories,
                           now=date.today().strftime('%Y-%m-%d'))


@app.route('/manage_recurring', methods=['GET', 'POST'])
@login_required
def manage_recurring():
    if request.method == 'POST':
        action = request.form.get('action')
        t_id = request.form.get('id')

        with sqlite3.connect(DB_FILE) as con:
            cur = con.cursor()
            if action == 'delete':
                cur.execute("UPDATE recurring_templates SET active = 0 WHERE id = ? AND user_id = ?", (t_id, current_user.id))
            elif action == 'edit':
                new_name = request.form.get('name')
                new_amount = request.form.get('amount')
                new_category = request.form.get('category') or None
                new_freq = request.form.get('frequency')
                new_end_date = request.form.get('end_date') or None
                cur.execute("""
                    UPDATE recurring_templates
                    SET name = ?, amount = ?, category = ?, frequency = ?, end_date = ?
                    WHERE id = ? AND user_id = ?
                """, (new_name, new_amount, new_category, new_freq, new_end_date, t_id, current_user.id))
            con.commit()

        return redirect(url_for('manage_recurring'))

    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM recurring_templates WHERE active = 1 AND user_id = ?", (current_user.id,))
        items = cur.fetchall()

    return render_template('manage_recurring.html', items=items)


@app.route('/add_entry', methods=['GET', 'POST'])
@login_required
def add_entry_page():
    if request.method == 'POST':
        form = request.form
        name = form.get('item_name', '').strip()
        date_str = form.get('date')
        trans_type = form.get('type')
        category = form.get('category')
        is_recurring = form.get('is_recurring') == 'on'
        frequency = form.get('frequency')
        end_date = form.get('end_date') or None

        if not name:
            flash('Item name is required.', 'error')
            return render_template('add_entry.html', categories=CATEGORIES_LIST.split(', '))

        try:
            amount = float(form.get('amount', ''))
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash('Please enter a valid amount greater than zero.', 'error')
            return render_template('add_entry.html', categories=CATEGORIES_LIST.split(', '))

        with sqlite3.connect(DB_FILE) as con:
            add_manual_transaction(name, amount, category, date_str, trans_type, is_recurring, frequency, end_date, current_user.id, con)
            con.commit()
        return redirect(url_for('spending_page'))

    return render_template('add_entry.html', categories=CATEGORIES_LIST.split(', '))


@app.route('/peer_insights')
@login_required
def peer_insights():
    monthly_data = get_monthly_overviews(current_user.id)
    current_month_spending = {}
    if monthly_data:
        for cat_data in monthly_data[0].get('categories', []):
            cat = cat_data['name']
            current_month_spending[cat] = current_month_spending.get(cat, 0) + cat_data['val']

    match_cats = request.args.getlist('match_cat')
    match_income = request.args.get('match_income', '1') == '1'

    insights = get_insights_with_tips(current_user.id, current_month_spending,
                                      match_cats=match_cats if match_cats else None,
                                      match_income=match_income)
    return jsonify({'insights': insights})


@app.route('/transactions')
@login_required
def transactions_page():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    month = request.args.get('month', '').strip()
    show_income = request.args.get('show_income', '0') == '1'

    results = search_transactions(current_user.id, query, category, month, show_income)
    categories = CATEGORIES_LIST.split(', ')

    return render_template('transactions.html',
                           results=results,
                           query=query,
                           selected_category=category,
                           selected_month=month,
                           show_income=show_income,
                           categories=categories)


@app.route('/predictions')
@login_required
def predictions_page():
    data = get_ml_predictions(current_user.id)
    return render_template('predictions.html', predictions=data['predictions'], mae=data['mae'], baseline_mae=data['baseline_mae'])


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return redirect(url_for('index'))

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    job_id = str(uuid.uuid4())
    q.enqueue(process_receipt_job, job_id, save_path, filename, job_id=job_id)
    return redirect(url_for('results_page', job_id=job_id))


@app.route('/results/<job_id>')
@login_required
def results_page(job_id):
    return render_template('results.html', job_id=job_id)


@app.route('/get-results/<job_id>')
@login_required
def get_results(job_id):
    try:
        result = get_temp_receipt_items(job_id)
        result['categories_list'] = CATEGORIES_LIST.split(', ')
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/finalize', methods=['POST'])
@login_required
def finalize_receipt():
    form = request.form
    receipt_filename = form.get('filename')
    receipt_date = form.get('receipt_date')
    index = 0
    corrected_items = []

    while f'item-name-{index}' in form:
        if f'delete-{index}' not in form:
            user_item = {
                'Item': form[f'item-name-{index}'],
                'Cost': form[f'cost-{index}'],
                'Category': form[f'category-{index}']
            }
            original_raw = form.get(f'raw-ocr-{index}', '')
            with sqlite3.connect(DB_FILE) as con:
                update_caches_from_correction(user_item, original_raw, con)
                con.commit()
            corrected_items.append(user_item)
        index += 1

    with sqlite3.connect(DB_FILE) as con:
        log_spending(corrected_items, receipt_filename, receipt_date, current_user.id, con)
        con.commit()

    return redirect(url_for('spending_page'))


@app.route('/check-username')
def check_username():
    username = request.args.get('username', '')
    with sqlite3.connect(DB_FILE) as con:
        cur = con.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        exists = cur.fetchone() is not None
    return jsonify({'exists': exists})


@app.route('/delete_transaction', methods=['POST'])
@login_required
def delete_transaction():
    transaction_id = request.form.get('id')
    if transaction_id:
        with sqlite3.connect(DB_FILE) as con:
            cur = con.cursor()
            cur.execute(
                "DELETE FROM spending_log WHERE id = ? AND user_id = ?",
                (transaction_id, current_user.id)
            )
            con.commit()
        flash('Transaction deleted.', 'success')
    return redirect(url_for('transactions_page'))


if __name__ == '__main__':
    app.run(debug=True)