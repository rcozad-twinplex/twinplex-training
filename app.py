import os
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, flash)
import database as db
import content as content_mod

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')


# ── Helpers ───────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') not in ('admin', 'trainer'):
            flash('Access restricted to trainers and admins.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return wrapped


def grade_quiz(questions, form_data):
    answers = []
    auto_correct = 0
    auto_total = 0

    for q in questions:
        idx = q['idx']
        qtype = q['type']

        if qtype == 'mc':
            given = form_data.get(f'q{idx}', '').strip().lower()
            correct = q['answer'].lower()
            is_correct = 1 if given == correct else 0
            auto_correct += is_correct
            auto_total += 1
            answers.append({'question_idx': idx, 'answer_given': given.upper(),
                             'auto_correct': is_correct})

        elif qtype == 'tf':
            given = form_data.get(f'q{idx}', '').strip().upper()
            correct = q['answer'].upper()
            is_correct = 1 if given == correct else 0
            auto_correct += is_correct
            auto_total += 1
            answers.append({'question_idx': idx, 'answer_given': given,
                             'auto_correct': is_correct})

        elif qtype == 'fill':
            blanks = q.get('blanks', 1)
            parts = [form_data.get(f'q{idx}_b{b}', '').strip() for b in range(blanks)]
            answers.append({'question_idx': idx, 'answer_given': ' | '.join(parts),
                             'auto_correct': None})

        elif qtype == 'list':
            n = q.get('parts', 1)
            parts = [form_data.get(f'q{idx}_p{p}', '').strip() for p in range(n)]
            answers.append({'question_idx': idx, 'answer_given': ' | '.join(parts),
                             'auto_correct': None})

    return answers, auto_correct, auto_total


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        emp_id = request.form.get('employee_id', '').strip()
        pin = request.form.get('pin', '').strip()
        user = db.verify_pin(emp_id, pin)
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            session['lang'] = user['lang_pref']
            next_url = request.form.get('next') or url_for('home')
            return redirect(next_url)
        flash('Invalid employee ID or PIN.', 'error')
    return render_template('login.html', next=request.args.get('next', ''))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/set-lang/<lang>')
@login_required
def set_lang(lang):
    if lang in ('en', 'es'):
        session['lang'] = lang
        db.update_lang(session['user_id'], lang)
    return redirect(request.referrer or url_for('home'))


# ── Home ──────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def home():
    sections = content_mod.get_modules_by_section()
    completions = {c['module_code']: c
                   for c in db.get_operator_completions(session['user_id'])}
    return render_template('home.html', sections=sections, completions=completions,
                           lang=session.get('lang', 'en'))


# ── Lesson ────────────────────────────────────────────────────────────────────

@app.route('/module/<code>')
@login_required
def lesson(code):
    mod = content_mod.get_module(code)
    if not mod:
        flash('Module not found.', 'error')
        return redirect(url_for('home'))

    lang = session.get('lang', 'en')
    html_content = content_mod.render_lesson(code, lang)
    db.mark_lesson_viewed(session['user_id'], code, lang)
    completion = db.get_or_create_completion(session['user_id'], code, lang)
    pcs = db.get_pc_results_map(completion['id'])

    return render_template('lesson.html', mod=mod, lesson_html=html_content,
                           completion=completion, pcs=pcs, lang=lang)


# ── Performance checks (generalized — quiz or checklist, any number) ───────────

@app.route('/module/<code>/pc/<int:num>', methods=['GET', 'POST'])
@login_required
def pc(code, num):
    mod = content_mod.get_module(code)
    check = content_mod.get_check(mod, num)
    if not check:
        flash(f'No Performance Check #{num} for this module.', 'error')
        return redirect(url_for('lesson', code=code))

    lang = session.get('lang', 'en')
    completion = db.get_or_create_completion(session['user_id'], code, lang)

    if check['type'] == 'quiz':
        questions = check['questions']
        if request.method == 'POST':
            answers, auto_correct, auto_total = grade_quiz(questions, request.form)
            db.save_quiz_answers(completion['id'], num, answers)
            db.upsert_quiz_submission(completion['id'], num, auto_correct, auto_total)
            return redirect(url_for('pc_result', code=code, num=num,
                                    completion_id=completion['id']))
        return render_template('quiz.html', mod=mod, check=check, num=num,
                               questions=questions, completion=completion, lang=lang)

    # checklist
    result = db.get_pc_result(completion['id'], num)
    state = db.get_checklist_state(completion['id'], num)
    trainers = db.get_trainers()
    return render_template('checklist.html', mod=mod, check=check, num=num,
                           checklist_data=check, completion=completion,
                           result=result, state=state, trainers=trainers, lang=lang)


@app.route('/module/<code>/pc/<int:num>/result/<int:completion_id>')
@login_required
def pc_result(code, num, completion_id):
    mod = content_mod.get_module(code)
    check = content_mod.get_check(mod, num)
    if not check or check['type'] != 'quiz':
        return redirect(url_for('lesson', code=code))

    completion = db.get_completion_by_id(completion_id)
    if not completion:
        return redirect(url_for('home'))

    answers = db.get_quiz_answers(completion_id, num)
    questions = check['questions']
    answer_map = {a['question_idx']: a for a in answers}
    result = db.get_pc_result(completion_id, num)
    trainers = db.get_trainers()

    return render_template('quiz_result.html', mod=mod, check=check, num=num,
                           questions=questions, answer_map=answer_map,
                           completion=completion, result=result,
                           trainers=trainers, lang=session.get('lang', 'en'))


@app.route('/module/<code>/pc/<int:num>/toggle', methods=['POST'])
@login_required
def pc_toggle(code, num):
    data = request.get_json()
    completion_id = data.get('completion_id')
    item_idx = int(data.get('item_idx', 0))
    passed = int(data.get('passed', 0))

    completion = db.get_completion_by_id(completion_id)
    if not completion or completion['operator_id'] != session['user_id']:
        return jsonify({'error': 'unauthorized'}), 403

    db.toggle_checklist_item(completion_id, num, item_idx, passed)
    return jsonify({'ok': True})


@app.route('/module/<code>/pc/<int:num>/signoff', methods=['POST'])
@login_required
def pc_signoff(code, num):
    mod = content_mod.get_module(code)
    check = content_mod.get_check(mod, num)
    if not check:
        return redirect(url_for('lesson', code=code))

    trainer_emp = request.form.get('trainer_id', '').strip()
    trainer_pin = request.form.get('trainer_pin', '').strip()
    passed = 1 if request.form.get('result') == 'pass' else 0
    comments = request.form.get('comments', '').strip()
    completion_id = int(request.form.get('completion_id'))

    trainer = db.verify_pin(trainer_emp, trainer_pin)
    if not trainer or trainer['role'] not in ('trainer', 'admin'):
        flash('Invalid trainer employee ID or PIN.', 'error')
        if check['type'] == 'quiz':
            return redirect(url_for('pc_result', code=code, num=num,
                                    completion_id=completion_id))
        return redirect(url_for('pc', code=code, num=num))

    score = max_auto = None
    if check['type'] == 'quiz':
        questions = check['questions']
        answers = db.get_quiz_answers(completion_id, num)
        max_auto = sum(1 for q in questions if q['type'] in ('mc', 'tf'))
        score = sum(1 for a in answers if a.get('auto_correct') == 1)

    db.sign_off_pc(completion_id, num, check['type'], trainer['id'],
                   passed, comments, score, max_auto)
    flash(f"PC#{num} signed off — {'PASSED' if passed else 'RE-CHECK REQUIRED'}.", 'success')
    return redirect(url_for('lesson', code=code))


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    completions = db.get_all_completions()
    sections = content_mod.get_modules_by_section()
    users = db.get_all_users()
    return render_template('admin.html', completions=completions,
                           sections=sections, users=users)


@app.route('/admin/operator/<int:operator_id>')
@admin_required
def admin_operator(operator_id):
    user = db.get_user(operator_id)
    if not user:
        flash('Operator not found.', 'error')
        return redirect(url_for('admin'))
    completions = db.get_operator_completions(operator_id)
    modules = content_mod.get_modules()
    mod_map = {m['code']: m for m in modules}
    return render_template('admin_operator.html', operator=user,
                           completions=completions, mod_map=mod_map)


@app.route('/admin/add-user', methods=['POST'])
@admin_required
def add_user():
    name = request.form.get('name', '').strip()
    emp_id = request.form.get('employee_id', '').strip()
    pin = request.form.get('pin', '').strip()
    role = request.form.get('role', 'operator')

    if not name or not emp_id or not pin:
        flash('All fields are required.', 'error')
    elif len(pin) < 4:
        flash('PIN must be at least 4 digits.', 'error')
    elif db.add_user(name, emp_id, pin, role):
        flash(f'User "{name}" added successfully.', 'success')
    else:
        flash(f'Employee ID "{emp_id}" already exists.', 'error')
    return redirect(url_for('admin'))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
