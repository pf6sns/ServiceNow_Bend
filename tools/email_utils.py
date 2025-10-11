"""
Email Utilities - Helper functions for email processing
"""

import re
import email
import logging
from typing import Dict, Any, List, Optional
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timedelta

from utils.logger import setup_logger

logger = setup_logger(__name__)

class EmailUtils:
    """Utility class for email processing and validation"""
    
    @staticmethod
    def validate_email_address(email_address: str) -> bool:
        """
        Validate email address format
        
        Args:
            email_address: Email address to validate
            
        Returns:
            bool: True if valid email format
        """
        if not email_address or not isinstance(email_address, str):
            return False
        
        # Basic email regex pattern
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email_address.strip()))
    
    @staticmethod
    def extract_email_from_header(header_value: str) -> tuple:
        """
        Extract name and email from email header
        
        Args:
            header_value: Email header value (e.g., "John Doe <john@example.com>")
            
        Returns:
            tuple: (name, email_address)
        """
        try:
            name, email_addr = parseaddr(header_value)
            return name.strip(), email_addr.strip()
        except Exception as e:
            logger.warning(f"Error parsing email header '{header_value}': {e}")
            return "", header_value.strip() if header_value else ""
    
    @staticmethod
    def decode_email_header(header_value: str) -> str:
        """
        Decode encoded email header (handles different encodings)
        
        Args:
            header_value: Encoded header value
            
        Returns:
            str: Decoded header string
        """
        if not header_value:
            return ""
        
        try:
            decoded_parts = decode_header(header_value)
            decoded_string = ""
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        part = part.decode(encoding, errors='ignore')
                    else:
                        part = part.decode('utf-8', errors='ignore')
                decoded_string += part
            
            return decoded_string.strip()
        except Exception as e:
            logger.warning(f"Error decoding header '{header_value}': {e}")
            return str(header_value)
    
    @staticmethod
    def extract_text_from_html(html_content: str, max_length: int = 500) -> str:
        """
        Extract plain text from HTML content
        
        Args:
            html_content: HTML content string
            max_length: Maximum length of extracted text
            
        Returns:
            str: Plain text content
        """
        try:
            # Remove HTML tags using regex (basic approach)
            text = re.sub(r'<[^>]+>', '', html_content)
            
            # Decode HTML entities
            import html
            text = html.unescape(text)
            
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Truncate if needed
            if len(text) > max_length:
                text = text[:max_length] + "..."
            
            return text
        except Exception as e:
            logger.warning(f"Error extracting text from HTML: {e}")
            return ""
    
    @staticmethod
    def extract_email_body(message: email.message.EmailMessage, max_preview_length: int = 200) -> Dict[str, str]:
        """
        Extract body content from email message
        
        Args:
            message: Email message object
            max_preview_length: Maximum length for preview text
            
        Returns:
            Dict containing plain_text, html_text, and preview
        """
        result = {
            "plain_text": "",
            "html_text": "",
            "preview": ""
        }
        
        try:
            if message.is_multipart():
                # Handle multipart messages
                for part in message.walk():
                    content_type = part.get_content_type()
                    content_disposition = part.get("Content-Disposition", "")
                    
                    # Skip attachments
                    if "attachment" in content_disposition:
                        continue
                    
                    if content_type == "text/plain" and not result["plain_text"]:
                        charset = part.get_content_charset() or 'utf-8'
                        content = part.get_payload(decode=True)
                        if content:
                            result["plain_text"] = content.decode(charset, errors='ignore')
                    
                    elif content_type == "text/html" and not result["html_text"]:
                        charset = part.get_content_charset() or 'utf-8'
                        content = part.get_payload(decode=True)
                        if content:
                            result["html_text"] = content.decode(charset, errors='ignore')
            else:
                # Handle single part messages
                content_type = message.get_content_type()
                charset = message.get_content_charset() or 'utf-8'
                content = message.get_payload(decode=True)
                
                if content:
                    if content_type == "text/plain":
                        result["plain_text"] = content.decode(charset, errors='ignore')
                    elif content_type == "text/html":
                        result["html_text"] = content.decode(charset, errors='ignore')
            
            # Create preview text
            if result["plain_text"]:
                result["preview"] = EmailUtils._create_text_preview(result["plain_text"], max_preview_length)
            elif result["html_text"]:
                plain_from_html = EmailUtils.extract_text_from_html(result["html_text"])
                result["preview"] = EmailUtils._create_text_preview(plain_from_html, max_preview_length)
            
        except Exception as e:
            logger.error(f"Error extracting email body: {e}")
        
        return result
    
    @staticmethod
    def _create_text_preview(text: str, max_length: int) -> str:
        """Create a preview from text content"""
        if not text:
            return ""
        
        # Clean up text
        lines = text.strip().split('\n')
        preview_lines = []
        
        for line in lines:
            clean_line = line.strip()
            # Skip empty lines and quoted text
            if clean_line and not clean_line.startswith('>'):
                preview_lines.append(clean_line)
            
            # Stop after getting enough content
            if len(' '.join(preview_lines)) >= max_length:
                break
        
        preview = ' '.join(preview_lines)
        
        if len(preview) > max_length:
            preview = preview[:max_length].rsplit(' ', 1)[0] + "..."
        
        return preview
    
    @staticmethod
    def is_auto_reply(message: email.message.EmailMessage) -> bool:
        """
        Check if email is an auto-reply/out-of-office message
        
        Args:
            message: Email message object
            
        Returns:
            bool: True if appears to be auto-reply
        """
        try:
            # Check headers that indicate auto-reply
            auto_reply_headers = [
                "Auto-Submitted",
                "X-Auto-Response-Suppress",
                "X-Autorespond",
                "X-Autoreply"
            ]
            
            for header in auto_reply_headers:
                if message.get(header):
                    return True
            
            # Check subject for common auto-reply patterns
            subject = EmailUtils.decode_email_header(message.get("Subject", "")).lower()
            auto_reply_subjects = [
                "out of office",
                "auto reply",
                "automatic reply",
                "vacation",
                "away from office",
                "currently unavailable",
                "delivery status notification"
            ]
            
            if any(pattern in subject for pattern in auto_reply_subjects):
                return True
            
            # Check for delivery failure messages
            if "mailer-daemon" in message.get("From", "").lower():
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking auto-reply status: {e}")
            return False
    
    @staticmethod
    def extract_attachments_info(message: email.message.EmailMessage) -> List[Dict[str, Any]]:
        """
        Extract information about email attachments (without downloading content)
        
        Args:
            message: Email message object
            
        Returns:
            List of attachment info dictionaries
        """
        attachments = []
        
        try:
            if message.is_multipart():
                for part in message.walk():
                    content_disposition = part.get("Content-Disposition", "")
                    
                    if "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            filename = EmailUtils.decode_email_header(filename)
                        
                        attachment_info = {
                            "filename": filename or "unknown",
                            "content_type": part.get_content_type(),
                            "size": len(part.get_payload(decode=True)) if part.get_payload(decode=True) else 0
                        }
                        attachments.append(attachment_info)
        
        except Exception as e:
            logger.warning(f"Error extracting attachment info: {e}")
        
        return attachments
    
    @staticmethod
    def sanitize_email_content(content: str) -> str:
        """
        Sanitize email content for safe processing
        
        Args:
            content: Raw email content
            
        Returns:
            str: Sanitized content
        """
        if not content:
            return ""
        
        try:
            # Remove potentially dangerous content
            sanitized = content
            
            # Remove script tags and their content
            sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove style tags and their content
            sanitized = re.sub(r'<style[^>]*>.*?</style>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove javascript: links
            sanitized = re.sub(r'javascript:[^"\']*', '', sanitized, flags=re.IGNORECASE)
            
            # Limit length to prevent memory issues
            if len(sanitized) > 10000:
                sanitized = sanitized[:10000] + "... [content truncated]"
            
            return sanitized
            
        except Exception as e:
            logger.warning(f"Error sanitizing email content: {e}")
            return content[:1000] if content else ""  # Fallback to truncated original
    
    @staticmethod
    def parse_email_date(date_string: str) -> Optional[datetime]:
        """
        Parse email date string to datetime object
        
        Args:
            date_string: Email date header string
            
        Returns:
            Optional[datetime]: Parsed datetime or None if parsing fails
        """
        try:
            return parsedate_to_datetime(date_string)
        except Exception as e:
            logger.warning(f"Error parsing email date '{date_string}': {e}")
            return None
    
    @staticmethod
    def is_recent_email(date_string: str, minutes_threshold: int = 15) -> bool:
        """
        Check if email is recent (within threshold)
        
        Args:
            date_string: Email date header string
            minutes_threshold: Threshold in minutes
            
        Returns:
            bool: True if email is recent
        """
        try:
            email_date = EmailUtils.parse_email_date(date_string)
            if not email_date:
                return False
            
            threshold_time = datetime.now(email_date.tzinfo) - timedelta(minutes=minutes_threshold)
            return email_date >= threshold_time
            
        except Exception as e:
            logger.warning(f"Error checking email recency: {e}")
            return False
    
    @staticmethod
    def extract_reply_to_info(message: email.message.EmailMessage) -> Dict[str, str]:
        """
        Extract reply-to information from email
        
        Args:
            message: Email message object
            
        Returns:
            Dict containing reply-to name and email
        """
        try:
            reply_to = message.get("Reply-To", "")
            if reply_to:
                name, email_addr = EmailUtils.extract_
                
                
                email_from_header(reply_to)
                return {"name": name, "email": email_addr}
            else:
                # Fall back to From header
                from_header = message.get("From", "")
                name, email_addr = EmailUtils.extract_email_from_header(from_header)
                return {"name": name, "email": email_addr}
                
        except Exception as e:
            logger.warning(f"Error extracting reply-to info: {e}")
            return {"name": "", "email": ""}