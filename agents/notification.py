"""
Notification Agent - Sends email notifications for ticket creation and closure
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from datetime import datetime

from utils.logger import setup_logger

logger = setup_logger(__name__)

class NotificationAgent:
    """Agent responsible for sending email notifications"""
    
    def __init__(self, config):
        self.config = config
        
        # Email configuration
        self.smtp_server = self.config.get_secret("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(self.config.get_secret("SMTP_PORT", "587"))
        self.smtp_username = self.config.get_secret("SMTP_USERNAME")
        self.smtp_password = self.config.get_secret("SMTP_PASSWORD")
        self.from_email = self.config.get_secret("FROM_EMAIL", self.smtp_username)
        self.from_name = self.config.get_setting("from_name", "IT Support System")
        
        # Email templates
        self.templates = self._load_email_templates()
    
    def _load_email_templates(self) -> Dict[str, str]:
        """Load email templates from config or use defaults"""
        templates = self.config.get_setting("email_templates", {})
        
        # Default templates if not provided
        default_templates = {
            "ticket_created": {
                "subject": "Support Ticket Created - {ticket_number}",
                "body": """
Dear {caller_name},

Your support request has been received and a ticket has been created.

Ticket Details:
- Ticket Number: {ticket_number}
- Subject: {short_description}
- Assigned to: {assigned_group}

Description:
{description}

You will receive updates as your ticket is processed. If you have any additional information or questions, please reply to this email and reference your ticket number.

Thank you,
{from_name}

---
This is an automated message. Please do not reply directly to this email.
Ticket ID: {ticket_number}
Created: {created_time}
"""
            },
            "ticket_closed": {
                "subject": "Support Ticket Resolved - {ticket_number}",
                "body": """
Dear {caller_name},

Your support ticket has been resolved and closed.

Ticket Details:
- Ticket Number: {ticket_number}
- Subject: {short_description}
- Resolution: {resolution_notes}
- Closed: {closed_time}

If you are satisfied with the resolution, no further action is required. If you need additional assistance or if the issue persists, please create a new support request.

Thank you for using our support services.

Best regards,
{from_name}

---
This is an automated message.
Ticket ID: {ticket_number}
Resolved: {closed_time}
"""
            },
            "ticket_updated": {
                "subject": "Support Ticket Updated - {ticket_number}",
                "body": """
Dear {caller_name},

Your support ticket has been updated.

Ticket Details:
- Ticket Number: {ticket_number}
- Subject: {short_description}
- Status: {status}
- Last Updated: {updated_time}

Update Notes:
{update_notes}

You will continue to receive updates as your ticket progresses.

Thank you,
{from_name}

---
This is an automated message.
Ticket ID: {ticket_number}
"""
            }
        }
        
        # Merge with config templates
        for template_name, template_data in default_templates.items():
            if template_name not in templates:
                templates[template_name] = template_data
        
        return templates
    
    def send_confirmation_email(self, recipient_email: str, ticket_number: str, 
                              short_description: str, **kwargs) -> Dict[str, Any]:
        """
        Send ticket creation confirmation email
        
        Args:
            recipient_email: Email address to send to
            ticket_number: ServiceNow ticket number
            short_description: Brief description of the issue
            **kwargs: Additional template variables
            
        Returns:
            Dict containing success status and details
        """
        try:
            logger.info(f"Sending confirmation email for ticket {ticket_number} to {recipient_email}")
            
            # Prepare template variables
            template_vars = {
                "caller_name": self._extract_name_from_email(recipient_email),
                "ticket_number": ticket_number,
                "short_description": short_description,
                "priority": kwargs.get("priority", "Medium"),
                "assigned_group": kwargs.get("assigned_group", "Support Team"),
                "description": kwargs.get("description", short_description),
                "from_name": self.from_name,
                "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **kwargs
            }
            
            # Get template
            template = self.templates.get("ticket_created", {})
            subject_template = template.get("subject", "Support Ticket Created - {ticket_number}")
            body_template = template.get("body", "Your ticket {ticket_number} has been created.")
            
            # Format email content
            subject = subject_template.format(**template_vars)
            body = body_template.format(**template_vars)
            
            # Send email
            result = self._send_email(recipient_email, subject, body)
            
            if result.get("success"):
                logger.info(f"Confirmation email sent successfully to {recipient_email}")
            else:
                logger.error(f"Failed to send confirmation email: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending confirmation email: {e}")
            return {"success": False, "error": str(e)}
    
    def send_closure_email(self, recipient_email: str, ticket_number: str, 
                          short_description: str, resolution_notes: str = "", **kwargs) -> Dict[str, Any]:
        """
        Send ticket closure notification email
        
        Args:
            recipient_email: Email address to send to
            ticket_number: ServiceNow ticket number
            short_description: Brief description of the issue
            resolution_notes: Resolution details
            **kwargs: Additional template variables
            
        Returns:
            Dict containing success status and details
        """
        try:
            logger.info(f"Sending closure email for ticket {ticket_number} to {recipient_email}")
            
            # Prepare template variables
            template_vars = {
                "caller_name": self._extract_name_from_email(recipient_email),
                "ticket_number": ticket_number,
                "short_description": short_description,
                "resolution_notes": resolution_notes or "Issue has been resolved.",
                "from_name": self.from_name,
                "closed_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **kwargs
            }
            
            # Get template
            template = self.templates.get("ticket_closed", {})
            subject_template = template.get("subject", "Support Ticket Resolved - {ticket_number}")
            body_template = template.get("body", "Your ticket {ticket_number} has been resolved.")
            
            # Format email content
            subject = subject_template.format(**template_vars)
            body = body_template.format(**template_vars)
            
            # Send email
            result = self._send_email(recipient_email, subject, body)
            
            if result.get("success"):
                logger.info(f"Closure email sent successfully to {recipient_email}")
            else:
                logger.error(f"Failed to send closure email: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending closure email: {e}")
            return {"success": False, "error": str(e)}
    
    def send_update_email(self, recipient_email: str, ticket_number: str, 
                         short_description: str, update_notes: str, **kwargs) -> Dict[str, Any]:
        """
        Send ticket update notification email
        
        Args:
            recipient_email: Email address to send to
            ticket_number: ServiceNow ticket number
            short_description: Brief description of the issue
            update_notes: Update details
            **kwargs: Additional template variables
            
        Returns:
            Dict containing success status and details
        """
        try:
            logger.info(f"Sending update email for ticket {ticket_number} to {recipient_email}")
            
            # Prepare template variables
            template_vars = {
                "caller_name": self._extract_name_from_email(recipient_email),
                "ticket_number": ticket_number,
                "short_description": short_description,
                "update_notes": update_notes,
                "status": kwargs.get("status", "In Progress"),
                "from_name": self.from_name,
                "updated_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **kwargs
            }
            
            # Get template
            template = self.templates.get("ticket_updated", {})
            subject_template = template.get("subject", "Support Ticket Updated - {ticket_number}")
            body_template = template.get("body", "Your ticket {ticket_number} has been updated.")
            
            # Format email content
            subject = subject_template.format(**template_vars)
            body = body_template.format(**template_vars)
            
            # Send email
            result = self._send_email(recipient_email, subject, body)
            
            if result.get("success"):
                logger.info(f"Update email sent successfully to {recipient_email}")
            else:
                logger.error(f"Failed to send update email: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error sending update email: {e}")
            return {"success": False, "error": str(e)}
    
    def _send_email(self, to_email: str, subject: str, body: str) -> Dict[str, Any]:
        """
        Send email using SMTP
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Email body content
            
        Returns:
            Dict containing success status and details
        """
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add body
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect to SMTP server
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Enable TLS encryption
                server.login(self.smtp_username, self.smtp_password)
                
                # Send email
                text = msg.as_string()
                server.sendmail(self.from_email, [to_email], text)
            
            logger.debug(f"Email sent successfully to {to_email}")
            return {"success": True, "message": "Email sent successfully"}
            
        except Exception as e:
            logger.error(f"SMTP error sending email to {to_email}: {e}")
            return {"success": False, "error": str(e)}
    
    def _extract_name_from_email(self, email: str) -> str:
        """Extract a display name from email address"""
        if not email or "@" not in email:
            return "Valued Customer"
        
        # Extract username part before @
        username = email.split("@")[0]
        
        # Try to make it more readable
        if "." in username:
            parts = username.split(".")
            name_parts = [part.capitalize() for part in parts if part]
            return " ".join(name_parts)
        elif "_" in username:
            parts = username.split("_")
            name_parts = [part.capitalize() for part in parts if part]
            return " ".join(name_parts)
        else:
            return username.capitalize()
    
    def send_bulk_notification(self, recipients: list, template_name: str, **template_vars) -> Dict[str, Any]:
        """
        Send bulk notifications to multiple recipients
        
        Args:
            recipients: List of email addresses
            template_name: Name of template to use
            **template_vars: Template variables
            
        Returns:
            Dict with overall success status and individual results
        """
        results = {
            "total": len(recipients),
            "successful": 0,
            "failed": 0,
            "details": []
        }
        
        for email in recipients:
            try:
                if template_name == "ticket_created":
                    result = self.send_confirmation_email(email, **template_vars)
                elif template_name == "ticket_closed":
                    result = self.send_closure_email(email, **template_vars)
                elif template_name == "ticket_updated":
                    result = self.send_update_email(email, **template_vars)
                else:
                    result = {"success": False, "error": f"Unknown template: {template_name}"}
                
                if result.get("success"):
                    results["successful"] += 1
                else:
                    results["failed"] += 1
                
                results["details"].append({
                    "email": email,
                    "success": result.get("success", False),
                    "error": result.get("error")
                })
                
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "email": email,
                    "success": False,
                    "error": str(e)
                })
        
        logger.info(f"Bulk notification complete: {results['successful']}/{results['total']} successful")
        return results
    
    def test_email_configuration(self) -> Dict[str, Any]:
        """Test email configuration and connectivity"""
        try:
            # Test SMTP connection
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
            
            logger.info("Email configuration test successful")
            return {"success": True, "message": "Email configuration is valid"}
            
        except Exception as e:
            logger.error(f"Email configuration test failed: {e}")
            return {"success": False, "error": str(e)}