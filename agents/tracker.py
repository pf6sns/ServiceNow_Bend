"""
Tracker Agent - Periodically checks ServiceNow ticket status and sends closure notifications
"""

import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timedelta
import json

from agents.servicenow import ServiceNowAgent
from agents.notification import NotificationAgent
from utils.logger import setup_logger

logger = setup_logger(__name__)

class TrackerAgent:
    """Agent responsible for tracking ticket status and sending closure notifications"""
    
    def __init__(self, config):
        self.config = config
        self.servicenow_agent = ServiceNowAgent(config)
        self.notification_agent = NotificationAgent(config)
        
        # In-memory storage for tracked tickets (in production, use database)
        self.tracked_tickets = {}
        
        # Status mappings (ServiceNow state values)
        self.status_mappings = {
            "1": "New",
            "2": "In Progress", 
            "3": "On Hold",
            "6": "Resolved",
            "7": "Closed",
            "8": "Canceled"
        }
        
        self.closed_states = ["6", "7", "8"]  # States considered closed
        
    def start_tracking_ticket(self, sys_id: str, ticket_number: str, caller_email: str, 
                            additional_data: Dict[str, Any] = None):
        """
        Start tracking a newly created ticket
        
        Args:
            sys_id: ServiceNow sys_id of the ticket
            ticket_number: Ticket number (e.g., INC0001234)
            caller_email: Email of the person who created the ticket
            additional_data: Additional ticket data for notifications
        """
        try:
            tracking_data = {
                "sys_id": sys_id,
                "ticket_number": ticket_number,
                "caller_email": caller_email,
                "created_time": datetime.now(),
                "last_checked": None,
                "last_status": None,
                "status_history": [],
                "notification_sent": False,
                "additional_data": additional_data or {}
            }
            
            self.tracked_tickets[sys_id] = tracking_data
            logger.info(f"Started tracking ticket {ticket_number} ({sys_id}) for {caller_email}")
            
        except Exception as e:
            logger.error(f"Error starting ticket tracking: {e}")
    
    async def check_all_tracked_tickets(self):
        """Check status of all tracked tickets"""
        if not self.tracked_tickets:
            logger.debug("No tickets to track")
            return
        
        logger.info(f"Checking status of {len(self.tracked_tickets)} tracked tickets")
        
        tickets_to_remove = []
        
        for sys_id, ticket_data in self.tracked_tickets.items():
            try:
                await self._check_single_ticket(sys_id, ticket_data)
                
                # Remove from tracking if closed and notification sent
                if (ticket_data.get("notification_sent") and 
                    ticket_data.get("last_status") in self.closed_states):
                    tickets_to_remove.append(sys_id)
                    
            except Exception as e:
                logger.error(f"Error checking ticket {ticket_data.get('ticket_number', sys_id)}: {e}")
        
        # Clean up completed tickets
        for sys_id in tickets_to_remove:
            ticket_number = self.tracked_tickets[sys_id].get("ticket_number", sys_id)
            del self.tracked_tickets[sys_id]
            logger.info(f"Removed completed ticket {ticket_number} from tracking")
        
        logger.info(f"Ticket status check complete. {len(tickets_to_remove)} tickets removed from tracking")
    
    async def _check_single_ticket(self, sys_id: str, ticket_data: Dict[str, Any]):
        """Check status of a single ticket"""
        try:
            ticket_number = ticket_data.get("ticket_number", sys_id)
            caller_email = ticket_data.get("caller_email", "")
            
            # Get current status from ServiceNow
            status_result = self.servicenow_agent.get_incident_status(sys_id)
            
            if not status_result.get("found"):
                logger.warning(f"Ticket {ticket_number} not found in ServiceNow")
                return
            
            current_status = status_result.get("state", "")
            current_status_name = self.status_mappings.get(current_status, "Unknown")
            
            # Update tracking data
            ticket_data["last_checked"] = datetime.now()
            previous_status = ticket_data.get("last_status")
            
            # Check if status changed
            if current_status != previous_status:
                logger.info(f"Status change for {ticket_number}: {previous_status} -> {current_status}")
                
                # Store the actual previous status for notifications BEFORE updating
                actual_previous_status = previous_status
                actual_previous_status_name = self.status_mappings.get(actual_previous_status, "Unknown") if actual_previous_status else "Unknown"
                
                # Add to status history (with correct previous status)
                ticket_data["status_history"].append({
                    "status": current_status,
                    "status_name": current_status_name,
                    "timestamp": datetime.now(),
                    "previous_status": actual_previous_status
                })
                
                # Send notification if ticket is closed
                if current_status in self.closed_states and not ticket_data.get("notification_sent"):
                    await self._send_closure_notification(sys_id, ticket_data, status_result)
                    ticket_data["notification_sent"] = True
                
                # Send update notification for ANY status change if configured
                elif self.config.get_setting("send_status_updates", False):
                    await self._send_status_update_notification(
                        sys_id, ticket_data, status_result, 
                        actual_previous_status, actual_previous_status_name
                    )
                
                # FINALLY update the stored status AFTER all notifications are sent
                ticket_data["last_status"] = current_status
                
        except Exception as e:
            logger.error(f"Error checking single ticket {sys_id}: {e}")

    async def _send_closure_notification(self, sys_id: str, ticket_data: Dict[str, Any], 
                                       status_result: Dict[str, Any]):
        """Send closure notification email"""
        try:
            ticket_number = ticket_data.get("ticket_number", "")
            caller_email = ticket_data.get("caller_email", "")
            additional_data = ticket_data.get("additional_data", {})
            
            if not caller_email:
                logger.warning(f"No caller email for ticket {ticket_number}, skipping closure notification")
                return
            
            # Prepare notification data
            short_description = additional_data.get("short_description", "Support Request")
            resolution_notes = status_result.get("resolution_notes", "Issue has been resolved.")
            
            # Send closure email
            result = self.notification_agent.send_closure_email(
                recipient_email=caller_email,
                ticket_number=ticket_number,
                short_description=short_description,
                resolution_notes=resolution_notes,
                status=self.status_mappings.get(status_result.get("state", ""), "Closed"),
                resolved_time=status_result.get("updated", "")
            )
            
            if result.get("success"):
                logger.info(f"Closure notification sent for ticket {ticket_number}")
            else:
                logger.error(f"Failed to send closure notification for {ticket_number}: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error sending closure notification for {sys_id}: {e}")
    
    async def _send_status_update_notification(self, sys_id: str, ticket_data: Dict[str, Any], 
                                         status_result: Dict[str, Any], 
                                         previous_status: str, previous_status_name: str):
        """Send status update notification email"""
        try:
            ticket_number = ticket_data.get("ticket_number", "")
            caller_email = ticket_data.get("caller_email", "")
            additional_data = ticket_data.get("additional_data", {})
            
            if not caller_email:
                logger.warning(f"No caller email for ticket {ticket_number}, skipping update notification")
                return
            
            # Prepare notification data - now using the passed previous status values
            short_description = additional_data.get("short_description", "Support Request")
            current_status = status_result.get("state", "")
            status_name = self.status_mappings.get(current_status, "Unknown")
            
            # Create update notes using the correct previous status
            update_notes = f"Ticket status changed to {status_name}"
            
            # Add resolution notes if available (for resolved/closed states)
            if current_status in ["6", "7"] and status_result.get("resolution_notes"):
                update_notes += f"\n\nResolution: {status_result.get('resolution_notes')}"
            
            # Add work notes if available
            work_notes = status_result.get("work_notes", "")
            if work_notes:
                update_notes += f"\n\nWork Notes: {work_notes}"
            
            # Send update email
            result = self.notification_agent.send_update_email(
                recipient_email=caller_email,
                ticket_number=ticket_number,
                short_description=short_description,
                update_notes=update_notes,
                status=status_name,
                updated_time=status_result.get("updated", "")
            )
            
            if result.get("success"):
                logger.info(f"Status update notification sent for ticket {ticket_number}")
            else:
                logger.error(f"Failed to send status update for {ticket_number}: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error sending status update notification for {sys_id}: {e}")
  
    def get_tracked_tickets_summary(self) -> Dict[str, Any]:
        """Get summary of currently tracked tickets"""
        try:
            summary = {
                "total_tracked": len(self.tracked_tickets),
                "by_status": {},
                "pending_notifications": 0,
                "oldest_ticket": None,
                "newest_ticket": None
            }
            
            if not self.tracked_tickets:
                return summary
            
            oldest_time = None
            newest_time = None
            
            for sys_id, ticket_data in self.tracked_tickets.items():
                # Count by status
                status = ticket_data.get("last_status", "Unknown")
                status_name = self.status_mappings.get(status, "Unknown")
                summary["by_status"][status_name] = summary["by_status"].get(status_name, 0) + 1
                
                # Count pending notifications
                if (ticket_data.get("last_status") in self.closed_states and 
                    not ticket_data.get("notification_sent")):
                    summary["pending_notifications"] += 1
                
                # Track oldest and newest
                created_time = ticket_data.get("created_time")
                if created_time:
                    if oldest_time is None or created_time < oldest_time:
                        oldest_time = created_time
                        summary["oldest_ticket"] = {
                            "ticket_number": ticket_data.get("ticket_number"),
                            "created": created_time.isoformat(),
                            "caller": ticket_data.get("caller_email")
                        }
                    
                    if newest_time is None or created_time > newest_time:
                        newest_time = created_time
                        summary["newest_ticket"] = {
                            "ticket_number": ticket_data.get("ticket_number"),
                            "created": created_time.isoformat(),
                            "caller": ticket_data.get("caller_email")
                        }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting tracked tickets summary: {e}")
            return {"error": str(e)}
    
    def stop_tracking_ticket(self, sys_id: str) -> bool:
        """
        Stop tracking a specific ticket
        
        Args:
            sys_id: ServiceNow sys_id of the ticket
            
        Returns:
            bool: True if ticket was being tracked and removed
        """
        try:
            if sys_id in self.tracked_tickets:
                ticket_number = self.tracked_tickets[sys_id].get("ticket_number", sys_id)
                del self.tracked_tickets[sys_id]
                logger.info(f"Stopped tracking ticket {ticket_number}")
                return True
            else:
                logger.warning(f"Ticket {sys_id} was not being tracked")
                return False
                
        except Exception as e:
            logger.error(f"Error stopping ticket tracking for {sys_id}: {e}")
            return False
    
    def get_ticket_status_history(self, sys_id: str) -> List[Dict[str, Any]]:
        """Get status history for a tracked ticket"""
        try:
            if sys_id not in self.tracked_tickets:
                return []
            
            ticket_data = self.tracked_tickets[sys_id]
            history = ticket_data.get("status_history", [])
            
            # Convert datetime objects to ISO strings for serialization
            formatted_history = []
            for entry in history:
                formatted_entry = entry.copy()
                if isinstance(formatted_entry.get("timestamp"), datetime):
                    formatted_entry["timestamp"] = formatted_entry["timestamp"].isoformat()
                formatted_history.append(formatted_entry)
            
            return formatted_history
            
        except Exception as e:
            logger.error(f"Error getting status history for {sys_id}: {e}")
            return []
    
    def cleanup_old_tickets(self, days_old: int = 30):
        """
        Clean up tracking data for very old tickets
        
        Args:
            days_old: Remove tickets older than this many days
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)
            tickets_to_remove = []
            
            for sys_id, ticket_data in self.tracked_tickets.items():
                created_time = ticket_data.get("created_time")
                if created_time and created_time < cutoff_date:
                    tickets_to_remove.append(sys_id)
            
            for sys_id in tickets_to_remove:
                ticket_number = self.tracked_tickets[sys_id].get("ticket_number", sys_id)
                del self.tracked_tickets[sys_id]
                logger.info(f"Cleaned up old ticket {ticket_number} from tracking")
            
            if tickets_to_remove:
                logger.info(f"Cleaned up {len(tickets_to_remove)} old tickets from tracking")
            else:
                logger.debug("No old tickets to clean up")
                
        except Exception as e:
            logger.error(f"Error during ticket cleanup: {e}")
    
    def force_check_ticket(self, sys_id: str) -> Dict[str, Any]:
        """
        Force an immediate status check for a specific ticket
        
        Args:
            sys_id: ServiceNow sys_id of the ticket
            
        Returns:
            Dict with check result
        """
        try:
            if sys_id not in self.tracked_tickets:
                return {"success": False, "error": "Ticket not being tracked"}
            
            ticket_data = self.tracked_tickets[sys_id]
            
            # Run the check
            asyncio.create_task(self._check_single_ticket(sys_id, ticket_data))
            
            return {
                "success": True,
                "message": f"Force check initiated for ticket {ticket_data.get('ticket_number', sys_id)}"
            }
            
        except Exception as e:
            logger.error(f"Error force checking ticket {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def export_tracking_data(self) -> Dict[str, Any]:
        """Export current tracking data (for backup/analysis)"""
        try:
            export_data = {
                "export_time": datetime.now().isoformat(),
                "total_tickets": len(self.tracked_tickets),
                "tickets": {}
            }
            
            for sys_id, ticket_data in self.tracked_tickets.items():
                # Convert datetime objects to ISO strings
                export_ticket = {}
                for key, value in ticket_data.items():
                    if isinstance(value, datetime):
                        export_ticket[key] = value.isoformat()
                    elif key == "status_history":
                        # Convert datetime in history entries
                        export_history = []
                        for entry in value:
                            export_entry = entry.copy()
                            if isinstance(export_entry.get("timestamp"), datetime):
                                export_entry["timestamp"] = export_entry["timestamp"].isoformat()
                            export_history.append(export_entry)
                        export_ticket[key] = export_history
                    else:
                        export_ticket[key] = value
                
                export_data["tickets"][sys_id] = export_ticket
            
            logger.info(f"Exported tracking data for {len(self.tracked_tickets)} tickets")
            return export_data
            
        except Exception as e:
            logger.error(f"Error exporting tracking data: {e}")
            return {"error": str(e)}
    
    def import_tracking_data(self, import_data: Dict[str, Any]) -> Dict[str, Any]:
        """Import tracking data (for restore/migration)"""
        try:
            imported_count = 0
            errors = []
            
            tickets_data = import_data.get("tickets", {})
            
            for sys_id, ticket_data in tickets_data.items():
                try:
                    # Convert ISO strings back to datetime objects
                    restored_ticket = {}
                    for key, value in ticket_data.items():
                        if key in ["created_time", "last_checked"] and isinstance(value, str):
                            restored_ticket[key] = datetime.fromisoformat(value)
                        elif key == "status_history" and isinstance(value, list):
                            # Convert datetime in history entries
                            restored_history = []
                            for entry in value:
                                restored_entry = entry.copy()
                                if isinstance(entry.get("timestamp"), str):
                                    restored_entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
                                restored_history.append(restored_entry)
                            restored_ticket[key] = restored_history
                        else:
                            restored_ticket[key] = value
                    
                    self.tracked_tickets[sys_id] = restored_ticket
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f"Error importing ticket {sys_id}: {str(e)}")
            
            logger.info(f"Imported tracking data for {imported_count} tickets")
            if errors:
                logger.warning(f"Import errors: {errors}")
            
            return {
                "success": True,
                "imported_count": imported_count,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error importing tracking data: {e}")
            return {"success": False, "error": str(e)}