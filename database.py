import os
import ssl
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
    ssl_ctx = ssl.create_default_context() if 'sslmode=require' in (url.query or '') else None
    return pg8000.dbapi.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip('/'),
        user=url.username,
        password=url.password,
        ssl_context=ssl_ctx,
    )


def _one(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _all(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


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


def save_pc1_answers(completion_id, answers):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM pc1_answers WHERE completion_id = %s", (completion_id,))
        for a in answers:
            cur.execute(
                "INSERT INTO pc1_answers (completion_id, question_idx, answer_given, auto_correct)"
                " VALUES (%s, %s, %s, %s)",
                (completion_id, a['question_idx'], a['answer_given'], a.get('auto_correct'))
            )
        conn.commit()
    finally:
        conn.close()


def get_pc1_answers(completion_id):
    conn = get_db()
    try:
        return _all(conn,
            "SELECT * FROM pc1_answers WHERE completion_id = %s ORDER BY question_idx",
            (completion_id,))
    finally:
        conn.close()


def save_pc1_result(completion_id, score, max_auto, trainer_id, passed, comments):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE completions
               SET pc1_score=%s, pc1_max_auto=%s, pc1_trainer_id=%s,
                   pc1_passed=%s, pc1_signed_at=CURRENT_TIMESTAMP, pc1_comments=%s,
                   pc1_submitted_at=COALESCE(pc1_submitted_at, CURRENT_TIMESTAMP)
               WHERE id = %s""",
            (score, max_auto, trainer_id, passed, comments, completion_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_pc1_submitted(completion_id, score, max_auto):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE completions SET pc1_submitted_at=CURRENT_TIMESTAMP,"
            " pc1_score=%s, pc1_max_auto=%s WHERE id=%s",
            (score, max_auto, completion_id)
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


def save_checklist_signoff(completion_id, check_num, trainer_id, passed, comments):
    conn = get_db()
    try:
        cur = conn.cursor()
        if check_num == 2:
            cur.execute(
                "UPDATE completions SET pc2_trainer_id=%s, pc2_passed=%s,"
                " pc2_signed_at=CURRENT_TIMESTAMP, pc2_comments=%s WHERE id=%s",
                (trainer_id, passed, comments, completion_id)
            )
        else:
            cur.execute(
                "UPDATE completions SET pc3_trainer_id=%s, pc3_passed=%s,"
                " pc3_signed_at=CURRENT_TIMESTAMP, pc3_comments=%s WHERE id=%s",
                (trainer_id, passed, comments, completion_id)
            )
        conn.commit()
    finally:
        conn.close()


def get_all_completions():
    conn = get_db()
    try:
        return _all(conn, """
            SELECT c.*, u.name as operator_name, u.employee_id,
                   t1.name as pc1_trainer_name,
                   t2.name as pc2_trainer_name,
                   t3.name as pc3_trainer_name
            FROM completions c
            JOIN users u ON c.operator_id = u.id
            LEFT JOIN users t1 ON c.pc1_trainer_id = t1.id
            LEFT JOIN users t2 ON c.pc2_trainer_id = t2.id
            LEFT JOIN users t3 ON c.pc3_trainer_id = t3.id
            ORDER BY u.name, c.module_code
        """)
    finally:
        conn.close()


def get_operator_completions(operator_id):
    conn = get_db()
    try:
        return _all(conn, """
            SELECT c.*,
                   t1.name as pc1_trainer_name,
                   t2.name as pc2_trainer_name,
                   t3.name as pc3_trainer_name
            FROM completions c
            LEFT JOIN users t1 ON c.pc1_trainer_id = t1.id
            LEFT JOIN users t2 ON c.pc2_trainer_id = t2.id
            LEFT JOIN users t3 ON c.pc3_trainer_id = t3.id
            WHERE c.operator_id = %s
            ORDER BY c.module_code
        """, (operator_id,))
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
