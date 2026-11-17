"""Small invite-only account store with persistent sessions and atomic usage limits."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from .wardrobe_settings import ROOT

SECRET = os.environ.get('APP_SECRET', '')
if len(SECRET) < 32:
    raise RuntimeError('请在 Render Environment 中设置至少32字符的 APP_SECRET，可使用 Generate。')
DB = ROOT / 'accounts.sqlite3'


def db():
    connection = sqlite3.connect(DB, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return salt + ':' + digest


def init():
    with db() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL, request_id TEXT NOT NULL, resource TEXT NOT NULL, UNIQUE(user_id,kind,request_id));
        CREATE TABLE IF NOT EXISTS attempts(address TEXT NOT NULL, created REAL NOT NULL);
        ''')
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        admin_name = os.environ.get('ADMIN_USERNAME', 'owner').lower()
        if admin_password:
            if len(admin_password) < 12 or not re.fullmatch(r'[a-z0-9_-]{3,32}', admin_name):
                raise RuntimeError('管理员用户名需3至32位英文/数字；ADMIN_PASSWORD 至少12字符。')
            found = conn.execute('SELECT * FROM users WHERE name=?', (admin_name,)).fetchone()
            if not found:
                conn.execute('INSERT INTO users VALUES(?,?,?,1)', (secrets.token_hex(16), admin_name, password_hash(admin_password)))
            elif not hmac.compare_digest(found['password'], password_hash(admin_password, found['password'].split(':')[0])):
                conn.execute('UPDATE users SET password=?,admin=1 WHERE id=?', (password_hash(admin_password), found['id']))
                conn.execute('DELETE FROM sessions WHERE user_id=?', (found['id'],))


def rate_limit(address):
    now = time.time()
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM attempts WHERE created<?', (now - 900,))
        count = conn.execute('SELECT COUNT(*) FROM attempts WHERE address=?', (address,)).fetchone()[0]
        if count >= 30:
            raise ValueError('登录或注册尝试过多，请15分钟后重试。')
        conn.execute('INSERT INTO attempts VALUES(?,?)', (address, now))


def register(name, password, invite):
    expected = os.environ.get('INVITE_CODE', '')
    if len(expected) < 8 or not hmac.compare_digest(invite.encode(), expected.encode()):
        raise ValueError('邀请码无效，请向网站管理员获取。')
    name = name.strip().lower()
    if name == os.environ.get('ADMIN_USERNAME', 'owner').lower():
        raise ValueError('此用户名已保留，请选择其他用户名。')
    if not re.fullmatch(r'[a-z0-9_-]{3,32}', name) or not 10 <= len(password) <= 128:
        raise ValueError('用户名需3至32位英文/数字/下划线；密码需10至128字符。')
    user_id = secrets.token_hex(16)
    try:
        with db() as conn:
            conn.execute('INSERT INTO users VALUES(?,?,?,0)', (user_id, name, password_hash(password)))
    except sqlite3.IntegrityError:
        raise ValueError('此用户名已被使用。') from None
    return {'id': user_id, 'name': name, 'admin': False}


def login(name, password):
    with db() as conn:
        row = conn.execute('SELECT * FROM users WHERE name=?', (name.strip().lower(),)).fetchone()
    # Hash even a missing user's password to avoid a cheap username timing oracle.
    stored = row['password'] if row else 'not-a-real-salt:' + '0' * 64
    if not hmac.compare_digest(stored, password_hash(password, stored.split(':')[0])):
        raise ValueError('用户名或密码不正确。')
    return {'id': row['id'], 'name': row['name'], 'admin': bool(row['admin'])}


def new_session(user):
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        conn.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], time.time() + 14 * 86400))
    return token


def user(token):
    if not token or len(token) > 200:
        return None
    with db() as conn:
        row = conn.execute('SELECT u.id,u.name,u.admin FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                           (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return {'id': row['id'], 'name': row['name'], 'admin': bool(row['admin'])} if row else None


def logout(token):
    with db() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def csrf(token):
    return hmac.new(SECRET.encode(), ('csrf:' + token).encode(), hashlib.sha256).hexdigest()


def guest(value=None):
    if value:
        nonce, sep, signature = value.partition('.')
        if sep and len(nonce) == 32 and hmac.compare_digest(signature, csrf('guest:' + nonce)):
            return value
    nonce = secrets.token_hex(16)
    return nonce + '.' + csrf('guest:' + nonce)


def receipt(user_id, kind, request_id):
    with db() as conn:
        row = conn.execute('SELECT resource FROM usage WHERE user_id=? AND kind=? AND request_id=?', (user_id, kind, request_id)).fetchone()
    return row[0] if row else None


def reserve_many(user_id, reservations):
    """Reserve design + optional auto-3D together so a failed limit cannot consume half a request."""
    day = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 8 * 3600))
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for kind, request_id, resource in reservations:
            if kind not in ('design', '3d') or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
                raise ValueError('请求编号无效，请刷新后重试。')
            previous = conn.execute('SELECT resource FROM usage WHERE user_id=? AND kind=? AND request_id=?', (user_id, kind, request_id)).fetchone()
            if previous:
                continue
            user_cap = int(os.environ.get('USER_DAILY_DESIGNS' if kind == 'design' else 'USER_DAILY_3D', '2'))
            global_cap = int(os.environ.get('GLOBAL_DAILY_DESIGNS' if kind == 'design' else 'GLOBAL_DAILY_3D', '10'))
            count = conn.execute('SELECT COUNT(*) FROM usage WHERE user_id=? AND kind=? AND day=?', (user_id, kind, day)).fetchone()[0]
            total = conn.execute('SELECT COUNT(*) FROM usage WHERE kind=? AND day=?', (kind, day)).fetchone()[0]
            if count >= user_cap or total >= global_cap:
                raise ValueError('今日生成额度已用完，请明天再试或联系管理员。')
            conn.execute('INSERT INTO usage(user_id,kind,day,request_id,resource) VALUES(?,?,?,?,?)', (user_id, kind, day, request_id, resource))


def reserve(user_id, kind, request_id, resource):
    reserve_many(user_id, [(kind, request_id, resource)])
    return resource
