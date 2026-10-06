"""Accès base de données (SQLite) et schéma."""
import json
import sqlite3

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS years (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY,
    year_id INTEGER NOT NULL REFERENCES years(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1 CHECK (weight > 0),
    position INTEGER NOT NULL DEFAULT 1,
    UNIQUE (year_id, name)
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY,
    year_id INTEGER NOT NULL REFERENCES years(id) ON DELETE CASCADE,
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    UNIQUE (year_id, name)
);

CREATE TABLE IF NOT EXISTS class_subjects (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    coef REAL NOT NULL DEFAULT 1 CHECK (coef > 0),
    teacher TEXT NOT NULL DEFAULT '',
    UNIQUE (class_id, subject_id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    matricule TEXT NOT NULL UNIQUE,
    last_name TEXT NOT NULL,
    first_name TEXT NOT NULL,
    sex TEXT NOT NULL DEFAULT '' CHECK (sex IN ('', 'M', 'F')),
    birth_date TEXT NOT NULL DEFAULT '',
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY,
    class_subject_id INTEGER NOT NULL REFERENCES class_subjects(id) ON DELETE CASCADE,
    period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'Devoir',
    date TEXT NOT NULL DEFAULT '',
    max_score REAL NOT NULL DEFAULT 20 CHECK (max_score > 0),
    weight REAL NOT NULL DEFAULT 1 CHECK (weight > 0)
);

CREATE TABLE IF NOT EXISTS grades (
    evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    score REAL,
    absent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (evaluation_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
CREATE INDEX IF NOT EXISTS idx_eval_cs ON evaluations(class_subject_id, period_id);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);
"""

DEFAULT_SETTINGS = {
    "school_name": "Mon établissement",
    "pass_mark": 10,
    "scale": 20,
    "mentions": [
        {"min": 16, "label": "Très bien"},
        {"min": 14, "label": "Bien"},
        {"min": 12, "label": "Assez bien"},
        {"min": 10, "label": "Passable"},
        {"min": 0, "label": "Insuffisant"},
    ],
}


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
    conn.commit()


def get_settings(conn):
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")}
