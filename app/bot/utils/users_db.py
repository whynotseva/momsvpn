"""
Local users database for MomsVPN
Handles subscriptions independently from Moms Club
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List

DB_PATH = os.path.join(os.path.dirname(__file__), "../../../data/users.db")


def init_db():
    """Initialize database and create tables"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            is_momsclub_member BOOLEAN DEFAULT FALSE,
            subscription_expires DATETIME,
            devices_limit INTEGER DEFAULT 2,
            added_by INTEGER,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()


def get_user(telegram_id: int) -> Optional[Dict]:
    """Get user by telegram ID"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def create_or_update_user(telegram_id: int, username: str = None, first_name: str = None, is_momsclub: bool = False) -> Dict:
    """Create or update user record"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    existing = get_user(telegram_id)
    
    if existing:
        c.execute('''
            UPDATE users SET 
                username = COALESCE(?, username),
                first_name = COALESCE(?, first_name),
                is_momsclub_member = ?,
                updated_at = ?
            WHERE telegram_id = ?
        ''', (username, first_name, is_momsclub, datetime.now(), telegram_id))
    else:
        c.execute('''
            INSERT INTO users (telegram_id, username, first_name, is_momsclub_member, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (telegram_id, username, first_name, is_momsclub, datetime.now()))
    
    conn.commit()
    conn.close()
    
    return get_user(telegram_id)


def add_subscription(telegram_id: int, days: int, added_by: int = None) -> bool:
    """Add subscription days to user. days=0 means unlimited"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    user = get_user(telegram_id)
    if not user:
        conn.close()
        return False
    
    if days == 0:
        # Unlimited - set to year 2100
        expires = datetime(2100, 1, 1)
    else:
        # Calculate new expiry
        current_expires = user.get('subscription_expires')
        if current_expires:
            try:
                base_date = datetime.fromisoformat(current_expires)
                if base_date < datetime.now():
                    base_date = datetime.now()
            except:
                base_date = datetime.now()
        else:
            base_date = datetime.now()
        
        expires = base_date + timedelta(days=days)
    
    c.execute('''
        UPDATE users SET 
            subscription_expires = ?,
            added_by = ?,
            updated_at = ?
        WHERE telegram_id = ?
    ''', (expires.isoformat(), added_by, datetime.now(), telegram_id))
    
    conn.commit()
    conn.close()
    return True


def set_devices_limit(telegram_id: int, limit: int) -> bool:
    """Set devices limit for user"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        UPDATE users SET 
            devices_limit = ?,
            updated_at = ?
        WHERE telegram_id = ?
    ''', (limit, datetime.now(), telegram_id))
    
    result = c.rowcount > 0
    conn.commit()
    conn.close()
    return result


def has_local_subscription(telegram_id: int) -> bool:
    """Check if user has valid local subscription"""
    user = get_user(telegram_id)
    if not user:
        return False
    
    expires = user.get('subscription_expires')
    if not expires:
        return False
    
    try:
        exp_date = datetime.fromisoformat(expires)
        return exp_date > datetime.now()
    except:
        return False


def get_non_momsclub_users(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get users who are not Moms Club members"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM users 
        WHERE is_momsclub_member = FALSE
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    
    rows = c.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def count_non_momsclub_users() -> int:
    """Count non-MC users"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_momsclub_member = FALSE")
    count = c.fetchone()[0]
    conn.close()
    
    return count


def get_all_users(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Get all users"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM users 
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    
    rows = c.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def count_all_users() -> int:
    """Count all users"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    
    return count


def search_user(query: str) -> Optional[Dict]:
    """Search user by username or telegram_id"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Try as telegram_id first
    try:
        tid = int(query.replace("@", ""))
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (tid,))
        row = c.fetchone()
        if row:
            conn.close()
            return dict(row)
    except ValueError:
        pass
    
    # Try as username
    username = query.replace("@", "").lower()
    c.execute("SELECT * FROM users WHERE LOWER(username) = ?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def get_users_with_subscription() -> List[Dict]:
    """Get all users who have an active local subscription"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM users 
        WHERE subscription_expires IS NOT NULL
        ORDER BY subscription_expires DESC
    ''')
    
    rows = c.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


# Initialize DB on import
init_db()
