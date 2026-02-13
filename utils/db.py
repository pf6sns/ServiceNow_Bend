
import sqlite3
import json
from datetime import datetime
import os
from typing import List, Dict, Any, Optional

DB_FILE = "tickets.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create tickets table
    c.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            sys_id TEXT PRIMARY KEY,
            ticket_number TEXT,
            caller_email TEXT,
            status TEXT,
            short_description TEXT,
            description TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            jira_ticket_id TEXT,
            priority TEXT,
            urgency TEXT,
            category TEXT,
            assigned_to TEXT,
            assignment_group TEXT
        )
    ''')
    
    # Create ticket_history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS ticket_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_sys_id TEXT,
            ticket_number TEXT,
            action TEXT,
            previous_status TEXT,
            new_status TEXT,
            changed_by TEXT,
            timestamp TIMESTAMP,
            details TEXT,
            FOREIGN KEY (ticket_sys_id) REFERENCES tickets (sys_id)
        )
    ''')
    
    conn.commit()
    conn.close()

def save_ticket(ticket_data: Dict[str, Any]):
    conn = get_db_connection()
    c = conn.cursor()
    
    now = datetime.now()
    
    try:
        c.execute('''
            INSERT OR REPLACE INTO tickets (
                sys_id, ticket_number, caller_email, status, short_description, 
                description, created_at, updated_at, jira_ticket_id,
                priority, urgency, category, assigned_to, assignment_group
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ticket_data.get('sys_id'),
            ticket_data.get('ticket_number'),
            ticket_data.get('caller_email'),
            ticket_data.get('status'),
            ticket_data.get('short_description'),
            ticket_data.get('description'),
            ticket_data.get('created_at', now),
            now,
            ticket_data.get('jira_ticket_id'),
            ticket_data.get('priority'),
            ticket_data.get('urgency'),
            ticket_data.get('category'),
            ticket_data.get('assigned_to'),
            ticket_data.get('assignment_group')
        ))
        conn.commit()
    except Exception as e:
        print(f"Error saving ticket: {e}")
    finally:
        conn.close()

def add_history(history_data: Dict[str, Any]):
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        c.execute('''
            INSERT INTO ticket_history (
                ticket_sys_id, ticket_number, action, previous_status, 
                new_status, changed_by, timestamp, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            history_data.get('ticket_sys_id'),
            history_data.get('ticket_number'),
            history_data.get('action'),
            history_data.get('previous_status'),
            history_data.get('new_status'),
            history_data.get('changed_by', 'System'),
            history_data.get('timestamp', datetime.now()),
            json.dumps(history_data.get('details', {}))
        ))
        conn.commit()
    except Exception as e:
        print(f"Error adding history: {e}")
    finally:
        conn.close()

def get_ticket(sys_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    ticket = c.execute('SELECT * FROM tickets WHERE sys_id = ?', (sys_id,)).fetchone()
    conn.close()
    return dict(ticket) if ticket else None

def get_ticket_by_number(ticket_number: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    ticket = c.execute('SELECT * FROM tickets WHERE ticket_number = ?', (ticket_number,)).fetchone()
    conn.close()
    return dict(ticket) if ticket else None

def get_all_tickets() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    tickets = c.execute('SELECT * FROM tickets ORDER BY updated_at DESC').fetchall()
    conn.close()
    return [dict(t) for t in tickets]

def get_ticket_history(sys_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    c = conn.cursor()
    history = c.execute('SELECT * FROM ticket_history WHERE ticket_sys_id = ? ORDER BY timestamp DESC', (sys_id,)).fetchall()
    conn.close()
    return [dict(h) for h in history]


def already_notified_for_status(ticket_sys_id: str, new_status: str) -> bool:
    """Return True if we already sent a notification (closure or status update) for this ticket with this status.
    Prevents duplicate emails when status is the same."""
    conn = get_db_connection()
    c = conn.cursor()
    row = c.execute(
        """SELECT 1 FROM ticket_history
           WHERE ticket_sys_id = ? AND action = 'NOTIFICATION_SENT' AND new_status = ?
           ORDER BY timestamp DESC LIMIT 1""",
        (ticket_sys_id, new_status),
    ).fetchone()
    conn.close()
    return row is not None


# Initialize DB on import
init_db()
