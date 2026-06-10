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
    modules = content_mod.get_modules()
    completions = {c['module_code']: c
                   for c in db.get_operator_completions(session['user_id'])}
    return render_template('home.html', modules=modules, completions=completions,
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

    return render_template('lesson.html', mod=mod, lesson_html=html_content,
                           completion=completion, lang=lang)


# ── PC#1 Quiz ─────────────────────────────────────────────────────────────────

@app.route('/module/<code>/quiz', methods=['GET', 'POST'])
@login_required
def quiz(code):
    mod = content_mod.get_module(code)
    if not mod or not mod.get('has_pc1'):
        flash('No PC#1 quiz for this module.', 'error')
        return redirect(url_for('lesson', code=code))

    lang = session.get('lang', 'en')
    completion = db.get_or_create_completion(session['user_id'], code, lang)
    questions = mod['pc1']['questions']

    if request.method == 'POST':
        answers, auto_correct, auto_total = grade_quiz(questions, request.form)
        db.save_pc1_answers(completion['id'], answers)
        db.update_pc1_submitted(completion['id'], auto_correct, auto_total)
        return redirect(url_for('quiz_result', code=code,
                                completion_id=completion['id']))

    return render_template('quiz.html', mod=mod, questions=questions,
                           completion=completion, lang=lang)


@app.route('/module/<code>/quiz/result/<int:completion_id>')
@login_required
def quiz_result(code, completion_id):
    mod = content_mod.get_module(code)
    if not mod:
        return redirect(url_for('home'))

    completion = db.get_completion_by_id(completion_id)
    if not completion:
        return redirect(url_for('home'))

    answers = db.get_pc1_answers(completion_id)
    questions = mod['pc1']['questions']
    answer_map = {a['question_idx']: a for a in answers}
    trainers = db.get_trainers()

    return render_template('quiz_result.html', mod=mod, questions=questions,
                           answer_map=answer_map, completion=completion,
                           trainers=trainers, lang=session.get('lang', 'en'))


@app.route('/module/<code>/quiz/result/<int:completion_id>/signoff', methods=['POST'])
@login_required
def quiz_signoff(code, completion_id):
    trainer_emp = request.form.get('trainer_id', '').strip()
    trainer_pin = request.form.get('trainer_pin', '').strip()
    passed = 1 if request.form.get('result') == 'pass' else 0
    comments = request.form.get('comments', '').strip()

    trainer = db.verify_pin(trainer_emp, trainer_pin)
    if not trainer or trainer['role'] not in ('trainer', 'admin'):
        flash('Invalid trainer employee ID or PIN.', 'error')
        return redirect(url_for('quiz_result', code=code, completion_id=completion_id))

    mod = content_mod.get_module(code)
    questions = mod['pc1']['questions']
    answers = db.get_pc1_answers(completion_id)
    auto_total = sum(1 for q in questions if q['type'] in ('mc', 'tf'))
    auto_correct = sum(1 for a in answers if a.get('auto_correct') == 1)

    db.save_pc1_result(completion_id, auto_correct, auto_total,
                       trainer['id'], passed, comments)
    flash(f"PC#1 signed off — {'PASSED' if passed else 'RE-CHECK REQUIRED'}.", 'success')
    return redirect(url_for('lesson', code=code))


# ── Checklists (PC#2 / PC#3) ─────────────────────────────────────────────────

@app.route('/module/<code>/checklist/<int:check_num>')
@login_required
def checklist(code, check_num):
    mod = content_mod.get_module(code)
    if not mod:
        return redirect(url_for('home'))

    key = f'pc{check_num}'
    if not mod.get(key):
        flash(f'No PC#{check_num} checklist for this module.', 'error')
        return redirect(url_for('lesson', code=code))

    lang = session.get('lang', 'en')
    completion = db.get_or_create_completion(session['user_id'], code, lang)
    state = db.get_checklist_state(completion['id'], check_num)
    trainers = db.get_trainers()

    return render_template('checklist.html', mod=mod, check_num=check_num,
                           checklist_data=mod[key], completion=completion,
                           state=state, trainers=trainers, lang=lang)


@app.route('/module/<code>/checklist/<int:check_num>/toggle', methods=['POST'])
@login_required
def checklist_toggle(code, check_num):
    data = request.get_json()
    completion_id = data.get('completion_id')
    item_idx = int(data.get('item_idx', 0))
    passed = int(data.get('passed', 0))

    completion = db.get_completion_by_id(completion_id)
    if not completion or completion['operator_id'] != session['user_id']:
        return jsonify({'error': 'unauthorized'}), 403

    db.toggle_checklist_item(completion_id, check_num, item_idx, passed)
    return jsonify({'ok': True})


@app.route('/module/<code>/checklist/<int:check_num>/signoff', methods=['POST'])
@login_required
def checklist_signoff(code, check_num):
    trainer_emp = request.form.get('trainer_id', '').strip()
    trainer_pin = request.form.get('trainer_pin', '').strip()
    passed = 1 if request.form.get('result') == 'pass' else 0
    comments = request.form.get('comments', '').strip()
    completion_id = int(request.form.get('completion_id'))

    trainer = db.verify_pin(trainer_emp, trainer_pin)
    if not trainer or trainer['role'] not in ('trainer', 'admin'):
        flash('Invalid trainer employee ID or PIN.', 'error')
        return redirect(url_for('checklist', code=code, check_num=check_num))

    db.save_checklist_signoff(completion_id, check_num, trainer['id'], passed, comments)
    flash(f"PC#{check_num} signed off — {'PASSED' if passed else 'RE-CHECK REQUIRED'}.", 'success')
    return redirect(url_for('lesson', code=code))


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    completions = db.get_all_completions()
    modules = content_mod.get_modules()
    users = db.get_all_users()
    return render_template('admin.html', completions=completions,
                           modules=modules, users=users)


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
