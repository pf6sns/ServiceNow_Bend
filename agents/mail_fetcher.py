"""
Mail Fetcher Agent - Fetches emails from Gmail using IMAP
Privacy-focused: reads subject only, falls back to first 2 lines of body if needed
"""

import imaplib
import email
import logging
from typing import List, Dict, Any
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime, timedelta, timezone
import imaplib
from email import message_from_bytes
from utils.logger import setup_logger

logger = setup_logger(__name__)

class MailFetcherAgent:
    """Agent responsible for fetching emails from Gmail via IMAP"""
    
    def __init__(self, config):
        self.config = config
        self.imap_server = "imap.gmail.com"
        self.imap_port = 993
        
    def _connect_to_gmail(self) -> imaplib.IMAP4_SSL:
        """Establish connection to Gmail IMAP server"""
        try:
            # Create IMAP connection
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            
            # Login with credentials
            email_user = self.config.get_secret("GMAIL_EMAIL")
            email_password = self.config.get_secret("GMAIL_APP_PASSWORD")
            
            mail.login(email_user, email_password)
            logger.info("Successfully connected to Gmail IMAP")
            
            return mail
            
        except Exception as e:
            logger.error(f"Failed to connect to Gmail: {e}")
            raise
    
    def _decode_header_value(self, header_value: str) -> str:
        """Decode email header value handling encoding"""
        if not header_value:
            return ""
            
        try:
            decoded_parts = decode_header(header_value)
            decoded_string = ""
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        part = part.decode(encoding)
                    else:
                        part = part.decode('utf-8', errors='ignore')
                decoded_string += part
                
            return decoded_string.strip()
        except Exception as e:
            logger.warning(f"Error decoding header: {e}")
            return str(header_value)
    
    def _extract_email_content(self, msg: email.message.EmailMessage) -> Dict[str, Any]:
        """Extract relevant content from email message (privacy-focused)"""
        try:
            # Extract basic info
            subject = self._decode_header_value(msg.get("Subject", ""))
            from_header = self._decode_header_value(msg.get("From", ""))
            date_header = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")
            
            # Debug logging
            logger.debug(f"Raw date header: '{date_header}'")
            logger.debug(f"Subject: '{subject}'")
            logger.debug(f"From: '{from_header}'")
            
            # Parse sender email
            sender_name, sender_email = parseaddr(from_header)
            
            # Check if this email should be ignored
            should_ignore = self._should_ignore_email(subject, sender_email)
            if should_ignore:
                logger.info(f"Ignoring system/bounce email from {sender_email}: {subject}")

            # Privacy-focused: only read subject initially
            email_data = {
                "subject": subject,
                "from": sender_email,
                "sender_name": sender_name,
                "date": date_header,
                "message_id": message_id,
                "body_preview": None,  # Only populated if subject is vague
                "ignore": should_ignore
            }
            
            # Check if subject is vague or empty (fallback to body preview)
            if self._is_subject_vague(subject):
                logger.info(f"Subject appears vague: '{subject}', extracting body preview")
                body_preview = self._extract_body_preview(msg)
                email_data["body_preview"] = body_preview
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error extracting email content: {e}")
            return {
                "subject": "Error extracting subject",
                "from": "unknown@unknown.com",
                "sender_name": "Unknown",
                "date": "",
                "message_id": "",
                "body_preview": None
            }
    
    def _should_ignore_email(self, subject: str, sender: str) -> bool:
        """Identify system emails, bounces, and automated notifications that should be ignored"""
        subject_lower = subject.lower().strip()
        sender_lower = sender.lower().strip()
        
        # 1. Block known system/bounce senders
        ignored_senders = [
            "mailer-daemon@googlemail.com",
            "mailer-daemon@gmail.com",
            "postmaster@",
            "postmaster@google.com",
            "no-reply@accounts.google.com",
            "cloudplatform-noreply@google.com",
            "mailer-daemon@googlemail.com"
        ]
        
        if any(ignored in sender_lower for ignored in ignored_senders):
            return True
            
        # 2. Block bounce-related subjects
        ignored_subjects = [
            "delivery status notification",
            "failure notice",
            "undeliverable:",
            "returned mail:",
            "out of office:",
            "automatic reply:",
            "vacation response:"
        ]
        
        if any(ignored in subject_lower for ignored in ignored_subjects):
            return True
            
        return False

    def _is_subject_vague(self, subject: str) -> bool:
        """Determine if email subject is too vague and needs body preview"""
        if not subject or len(subject.strip()) < 3:
            return True
            
        vague_subjects = [
            "hi", "hello", "hey", "urgent", "help", "issue", "problem",
            "question", "request", "support", "fwd:", "fw:", "re:",
            "untitled", "no subject", "(no subject)", "important"
        ]
        
        subject_lower = subject.lower().strip()
        
        # Check if subject is just vague words
        if subject_lower in vague_subjects:
            return True
            
        # Check if subject is very short and generic
        if len(subject_lower) < 10 and any(word in subject_lower for word in vague_subjects[:8]):
            return True
            
        return False
    
    def _extract_body_preview(self, msg: email.message.EmailMessage, max_lines: int = 2) -> str:
        """Extract first few lines of email body for vague subjects (privacy-focused)"""
        try:
            body_text = ""
            
            if msg.is_multipart():
                # Handle multipart messages
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or 'utf-8'
                        body_content = part.get_payload(decode=True)
                        if body_content:
                            body_text = body_content.decode(charset, errors='ignore')
                            break
            else:
                # Handle single part messages
                charset = msg.get_content_charset() or 'utf-8'
                body_content = msg.get_payload(decode=True)
                if body_content:
                    body_text = body_content.decode(charset, errors='ignore')
            
            if body_text:
                # Extract first 2 lines only for privacy
                lines = body_text.strip().split('\n')
                preview_lines = []
                
                for line in lines[:max_lines]:
                    clean_line = line.strip()
                    if clean_line and not clean_line.startswith('>'):  # Skip quoted text
                        preview_lines.append(clean_line)
                
                return ' '.join(preview_lines)[:200]  # Limit to 200 chars
                
        except Exception as e:
            logger.error(f"Error extracting body preview: {e}")
            
        return ""
    
    
    def fetch_unread_emails(self, since_time: datetime = None) -> List[Dict[str, Any]]:
        """Fetch unread emails from Gmail inbox within the specified time window (default last 10 minutes in IST)"""
        emails = []
        mail = None
        
        try:
            # Define IST timezone
            IST = timezone(timedelta(hours=5, minutes=30))

            # Default: look back 10 minutes in IST
            if since_time is None:
                since_time = datetime.now(IST) - timedelta(minutes=10)
            else:
                if since_time.tzinfo is None:
                    since_time = since_time.replace(tzinfo=IST)
                else:
                    since_time = since_time.astimezone(IST)

            # Convert since_time to UTC for Gmail comparison
            since_time = since_time.astimezone(timezone.utc)
            
            logger.info(f"Searching for emails since (IST): {since_time.astimezone(IST)}")
            
            # Connect to Gmail
            mail = self._connect_to_gmail()
            mail.select("INBOX")
            
            # IMAP searches by date (not exact time), so use date part
            search_date = since_time.strftime("%d-%b-%Y")
            
            # Search unread emails since the given date
            search_criteria = f'(UNSEEN SINCE {search_date})'
            result, message_numbers = mail.search(None, search_criteria)
            
            if result != 'OK':
                logger.warning("Failed to search emails")
                return emails
            
            message_ids = message_numbers[0].split()
            logger.info(f"Found {len(message_ids)} unread emails since {search_date}")
            
            if not message_ids:
                return emails
            
            # Process each email
            for msg_id in message_ids:
                try:
                    msg_id_str = msg_id.decode()
                    
                    # Fetch INTERNALDATE
                    result, internaldate_data = mail.fetch(msg_id, '(INTERNALDATE)')
                    if result != 'OK':
                        continue
                    
                    internal_date = None
                    if internaldate_data and internaldate_data[0]:
                        import re
                        response_line = internaldate_data[0]
                        if isinstance(response_line, tuple):
                            response_line = response_line[0]
                        
                        response_str = response_line.decode('utf-8', errors='ignore')
                        date_match = re.search(r'INTERNALDATE "([^"]+)"', response_str)
                        if date_match:
                            internal_date_str = date_match.group(1)
                            internal_date = datetime.strptime(internal_date_str, '%d-%b-%Y %H:%M:%S %z')
                    
                    if internal_date:
                        internal_date_utc = internal_date.astimezone(timezone.utc)
                        internal_date_ist = internal_date.astimezone(IST)

                        if internal_date_utc >= since_time:
                            # Fetch full email
                            result, msg_data = mail.fetch(msg_id, "(RFC822)")
                            if result != 'OK':
                                continue
                            
                            raw_email = msg_data[0][1]
                            email_message = message_from_bytes(raw_email)
                            email_data = self._extract_email_content(email_message)
                            email_data["imap_id"] = msg_id_str
                            emails.append(email_data)
                            logger.info(f"✅ Included email ({internal_date_ist} IST): {email_data['subject'][:50]}...")
                        else:
                            logger.info(f"❌ Excluded (too old): {internal_date_ist} IST")
                
                except Exception as e:
                    logger.error(f"Error processing email {msg_id}: {e}")
                    continue
            
            logger.info(f"Successfully fetched {len(emails)} emails from the last 10 minutes (IST)")
            return emails
        
        except Exception as e:
            logger.error(f"Error in fetch_unread_emails: {e}")
            return emails
        
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception as e:
                    logger.warning(f"Error closing IMAP connection: {e}")


    def mark_email_as_read(self, imap_id: str):
        """Mark specific email as read"""
        mail = None
        try:
            # Need to create new connection as previous one might be closed
            mail = self._connect_to_gmail()
            mail.select("INBOX")
            
            # Mark as seen
            mail.store(imap_id, '+FLAGS', '\\Seen')
            logger.debug(f"Marked email {imap_id} as read")
            
        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except:
                    pass

    def fetch_all_recent_emails(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch the most recent N emails regardless of read status (for manual sync)"""
        emails = []
        mail = None
        try:
            logger.info(f"Fetching last {limit} emails from Gmail (manual sync deep probe)...")
            mail = self._connect_to_gmail()
            mail.select("INBOX")
            
            # Search all emails
            # 'ALL' might be too much, so we fetch messages by ID (highest ID = newest)
            # Fetch last N message IDs directly
            
            # Get number of messages
            status, response = mail.search(None, 'ALL')
            if status != 'OK':
                return []
                
            all_ids = response[0].split()
            last_n_ids = all_ids[-limit:] if len(all_ids) > limit else all_ids
            # Reverse to process newest first (optional, but logical for "recent")
            # But we usually process list in order.
            
            logger.info(f"Found {len(last_n_ids)} recent emails")
            
            for msg_id in last_n_ids:
                try:
                    msg_id_str = msg_id.decode()
                    result, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if result != 'OK':
                        continue
                        
                    raw_email = msg_data[0][1]
                    email_message = message_from_bytes(raw_email)
                    email_data = self._extract_email_content(email_message)
                    email_data["imap_id"] = msg_id_str
                    emails.append(email_data)
                    logger.info(f"Fetched email: {email_data['subject'][:30]}...")
                except Exception as e:
                    logger.error(f"Error fetching email {msg_id}: {e}")
                    
            return emails
            
        except Exception as e:
            logger.error(f"Error in fetch_all_recent_emails: {e}")
            return []
        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except:
                    pass