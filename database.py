import os
import ssl
import datetime
import pg8000.dbapi
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    url = urlparse(DATABASE_URL)
    ssl_ctx = None
    if 'sslmode=require' in (url.query or ''):
        # Supabase's pooler presents a self-signed cert in its chain, so the
        # default verifying context rejects it. Encrypt but skip verification.
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    return pg8000.dbapi.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip('/'),
        user=url.username,
        password=url.password,
        ssl_context=ssl_ctx,
    )


def _conv(v):
    """Normalize DB values for templates: timestamps -> ISO strings so the
    templates can slice them (e.g. signed_at[:10])."""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return v


def _row(cols, row):
    return {c: _conv(v) for c, v in zip(cols, row)}


def _one(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return _row(cols, row)


def _all(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [_row(cols, row) for row in cur.fetchall()]


def verify_pin(employee_id, pin):
    conn = get_db()
    try:
        row = _one(conn,
            "SELECT * FROM users WHERE employee_id = %s AND active = 1",
            (employee_id,))
        if row and check_password_hash(row['pin_hash'], pin):
            return row
        return None
    finally:
        conn.close()


def get_user(user_id):
    conn = get_db()
    try:
        return _one(conn, "SELECT * FROM users WHERE id = %s", (user_id,))
    finally:
        conn.close()


def get_all_operators():
    conn = get_db()
    try:
        return _all(conn,
            "SELECT * FROM users WHERE role = 'operator' AND active = 1 ORDER BY name")
    finally:
        conn.close()


def get_all_users():
    conn = get_db()
    try:
        return _all(conn,
            "SELECT * FROM users WHERE active = 1 ORDER BY role, name")
    finally:
        conn.close()


def add_user(name, employee_id, pin, role='operator'):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (name, employee_id, pin_hash, role) VALUES (%s, %s, %s, %s)",
            (name, employee_id, generate_password_hash(pin), role)
        )
        conn.commit()
        return True
    except pg8000.dbapi.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def update_lang(user_id, lang):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET lang_pref = %s WHERE id = %s", (lang, user_id))
        conn.commit()
    finally:
        conn.close()


def get_or_create_completion(operator_id, module_code, lang):
    conn = get_db()
    try:
        row = _one(conn,
            "SELECT * FROM completions WHERE operator_id = %s AND module_code = %s",
            (operator_id, module_code))
        if not row:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO completions (operator_id, module_code, lang_used) VALUES (%s, %s, %s)",
                (operator_id, module_code, lang)
            )
            conn.commit()
            row = _one(conn,
                "SELECT * FROM completions WHERE operator_id = %s AND module_code = %s",
                (operator_id, module_code))
        return row
    finally:
        conn.close()


def mark_lesson_viewed(operator_id, module_code, lang):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO completions (operator_id, module_code, lang_used, lesson_viewed)
               VALUES (%s, %s, %s, 1)
               ON CONFLICT (operator_id, module_code)
               DO UPDATE SET lesson_viewed = 1""",
            (operator_id, module_code, lang)
        )
        conn.commit()
    finally:
        conn.close()


def get_completion_by_id(completion_id):
    conn = get_db()
    try:
        return _one(conn, "SELECT * FROM completions WHERE id = %s", (completion_id,))
    finally:
        conn.close()


# ── Performance checks (generalized: any number per module) ──────────────────

def get_pc_result(completion_id, pc_num):
    conn = get_db()
    try:
        return _one(conn,
            "SELECT * FROM pc_results WHERE completion_id=%s AND pc_num=%s",
            (completion_id, pc_num))
    finally:
        conn.close()


def get_pc_results_map(completion_id):
    """All performance-check results for a completion, keyed by pc_num."""
    conn = get_db()
    try:
        rows = _all(conn,
            "SELECT * FROM pc_results WHERE completion_id=%s", (completion_id,))
        return {r['pc_num']: r for r in rows}
    finally:
        conn.close()


def _attach_pc_results(conn, completions):
    """Attach a 'pcs' dict {pc_num: result-row(+trainer_name)} to each completion."""
    if not completions:
        return completions
    ids = tuple({c['id'] for c in completions})
    placeholders = ','.join(['%s'] * len(ids))
    rows = _all(conn, f"""
        SELECT r.*, t.name AS trainer_name
        FROM pc_results r
        LEFT JOIN users t ON r.trainer_id = t.id
        WHERE r.completion_id IN ({placeholders})
    """, ids)
    by_completion = {}
    for r in rows:
        by_completion.setdefault(r['completion_id'], {})[r['pc_num']] = r
    for c in completions:
        c['pcs'] = by_completion.get(c['id'], {})
    return completions


def save_quiz_answers(completion_id, pc_num, answers):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM quiz_answers WHERE completion_id=%s AND pc_num=%s",
            (completion_id, pc_num))
        for a in answers:
            cur.execute(
                "INSERT INTO quiz_answers (completion_id, pc_num, question_idx,"
                " answer_given, auto_correct) VALUES (%s, %s, %s, %s, %s)",
                (completion_id, pc_num, a['question_idx'],
                 a['answer_given'], a.get('auto_correct'))
            )
        conn.commit()
    finally:
        conn.close()


def get_quiz_answers(completion_id, pc_num):
    conn = get_db()
    try:
        return _all(conn,
            "SELECT * FROM quiz_answers WHERE completion_id=%s AND pc_num=%s"
            " ORDER BY question_idx",
            (completion_id, pc_num))
    finally:
        conn.close()


def upsert_quiz_submission(completion_id, pc_num, score, max_auto):
    """Record a quiz submission (auto-graded portion) as pending sign-off."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pc_results (completion_id, pc_num, pc_type,
                   submitted_at, score, max_auto)
               VALUES (%s, %s, 'quiz', CURRENT_TIMESTAMP, %s, %s)
               ON CONFLICT (completion_id, pc_num)
               DO UPDATE SET submitted_at=CURRENT_TIMESTAMP,
                   score=EXCLUDED.score, max_auto=EXCLUDED.max_auto""",
            (completion_id, pc_num, score, max_auto)
        )
        conn.commit()
    finally:
        conn.close()


def sign_off_pc(completion_id, pc_num, pc_type, trainer_id, passed, comments,
                score=None, max_auto=None):
    """Trainer sign-off for any performance check (quiz or checklist)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pc_results (completion_id, pc_num, pc_type, score, max_auto,
                   submitted_at, trainer_id, passed, signed_at, comments)
               VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, CURRENT_TIMESTAMP, %s)
               ON CONFLICT (completion_id, pc_num)
               DO UPDATE SET pc_type=EXCLUDED.pc_type,
                   trainer_id=EXCLUDED.trainer_id, passed=EXCLUDED.passed,
                   signed_at=CURRENT_TIMESTAMP, comments=EXCLUDED.comments,
                   submitted_at=COALESCE(pc_results.submitted_at, CURRENT_TIMESTAMP)""",
            (completion_id, pc_num, pc_type, score, max_auto,
             trainer_id, passed, comments)
        )
        conn.commit()
    finally:
        conn.close()


def get_checklist_state(completion_id, check_num):
    conn = get_db()
    try:
        rows = _all(conn,
            "SELECT item_idx, passed FROM checklist_items"
            " WHERE completion_id=%s AND check_num=%s",
            (completion_id, check_num))
        return {r['item_idx']: r['passed'] for r in rows}
    finally:
        conn.close()


def toggle_checklist_item(completion_id, check_num, item_idx, passed):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO checklist_items (completion_id, check_num, item_idx, passed)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (completion_id, check_num, item_idx)
               DO UPDATE SET passed=%s""",
            (completion_id, check_num, item_idx, passed, passed)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_completions():
    conn = get_db()
    try:
        rows = _all(conn, """
            SELECT c.*, u.name as operator_name, u.employee_id
            FROM completions c
            JOIN users u ON c.operator_id = u.id
            ORDER BY u.name, c.module_code
        """)
        return _attach_pc_results(conn, rows)
    finally:
        conn.close()


def get_operator_completions(operator_id):
    conn = get_db()
    try:
        rows = _all(conn,
            "SELECT * FROM completions WHERE operator_id = %s ORDER BY module_code",
            (operator_id,))
        return _attach_pc_results(conn, rows)
    finally:
        conn.close()


def get_trainers():
    conn = get_db()
    try:
        return _all(conn,
            "SELECT id, name, employee_id FROM users"
            " WHERE role IN ('trainer','admin') AND active = 1 ORDER BY name")
    finally:
        conn.close()
