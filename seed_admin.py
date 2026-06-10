"""
Run once after setting up the Supabase schema to create the first admin account.
Requires DATABASE_URL in .env or environment.

Usage:
    python seed_admin.py
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg2
from werkzeug.security import generate_password_hash

name = input("Admin name [Admin]: ").strip() or "Admin"
emp_id = input("Employee ID [admin]: ").strip() or "admin"
pin = input("PIN (min 4 digits): ").strip()

if len(pin) < 4:
    print("PIN must be at least 4 characters.")
    raise SystemExit(1)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
try:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (name, employee_id, pin_hash, role)"
            " VALUES (%s, %s, %s, 'admin')"
            " ON CONFLICT (employee_id) DO NOTHING",
            (name, emp_id, generate_password_hash(pin))
        )
        if cur.rowcount:
            print(f"Admin '{emp_id}' created.")
        else:
            print(f"Employee ID '{emp_id}' already exists — no changes made.")
    conn.commit()
finally:
    conn.close()
