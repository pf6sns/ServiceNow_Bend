"""
Tracker Agent - Periodically checks ServiceNow ticket status and sends closure notifications
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json

from agents.servicenow import ServiceNowAgent
from agents.notification import NotificationAgent
from utils.logger import setup_logger
from utils.db import save_ticket, get_ticket, get_all_tickets, add_history, get_ticket_history

logger = setup_logger(__name__)

class TrackerAgent:
    """Agent responsible for tracking ticket status and sending closure notifications"""
    
    def __init__(self, config):
        self.config = config
        self.servicenow_agent = ServiceNowAgent(config)
        self.notification_agent = NotificationAgent(config)
        
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
            additional_data = additional_data or {}

            # Normalize Jira ticket reference (can be a key string or a nested dict from the Jira backend)
            jira_ticket_raw = additional_data.get("jira_ticket")
            jira_ticket_id = None

            if isinstance(jira_ticket_raw, dict):
                # Common shape from Jira-Backend /jira/auto-assign:
                # { "message": "...", "data": { "issue": "KEY-123", "assigned_to": "..." } }
                data_part = jira_ticket_raw.get("data")
                if isinstance(data_part, dict):
                    jira_ticket_id = data_part.get("issue") or data_part.get("key")
                else:
                    # Sometimes we might already have {"issue": "..."} or {"key": "..."}
                    jira_ticket_id = jira_ticket_raw.get("issue") or jira_ticket_raw.get("key")

                if jira_ticket_id is not None:
                    jira_ticket_id = str(jira_ticket_id)
            elif jira_ticket_raw is not None:
                # Plain string or other primitive
                jira_ticket_id = str(jira_ticket_raw)
            
            # Prepare ticket data for DB
            ticket_data = {
                "sys_id": sys_id,
                "ticket_number": ticket_number,
                "caller_email": caller_email,
                "status": "1", # Default to New
                "short_description": additional_data.get("short_description", ""),
                "description": additional_data.get("description", ""),
                "created_at": datetime.now(),
                "jira_ticket_id": jira_ticket_id,
                "priority": additional_data.get("priority"),
                "urgency": additional_data.get("urgency"),
                "category": additional_data.get("category_name"),
            }
            
            save_ticket(ticket_data)
            
            # Add initial history
            add_history({
                "ticket_sys_id": sys_id,
                "ticket_number": ticket_number,
                "action": "TRACKING_STARTED",
                "previous_status": None,
                "new_status": "1",
                "changed_by": "System",
                "details": {"message": f"Started tracking ticket {ticket_number}"}
            })
            
            logger.info(f"Started tracking ticket {ticket_number} ({sys_id}) for {caller_email}")
            
        except Exception as e:
            logger.error(f"Error starting ticket tracking: {e}")
    
    async def check_all_tracked_tickets(self):
        """Check status of all tracked tickets"""
        tickets = get_all_tickets()
        
        if not tickets:
            logger.debug("No tickets to track")
            return
        
        # Filter for active tickets only (not closed/resolved, or recently closed)
        active_tickets = [t for t in tickets if t['status'] not in self.closed_states]
        
        logger.info(f"Checking status of {len(active_tickets)} active tickets")
        
        for ticket in active_tickets:
            try:
                # Convert active DB row to dict for processing
                ticket_data = dict(ticket)
                sys_id = ticket_data.get('sys_id')
                
                await self._check_single_ticket(sys_id, ticket_data)
                    
            except Exception as e:
                logger.error(f"Error checking ticket {ticket.get('ticket_number')}: {e}")
        
    
    async def _check_single_ticket(self, sys_id: str, ticket_data: Dict[str, Any]):
        """Check status of a single ticket"""
        try:
            ticket_number = ticket_data.get("ticket_number", sys_id)
            
            # Get current status from ServiceNow
            status_result = self.servicenow_agent.get_incident_status(sys_id)
            
            if not status_result.get("found"):
                logger.warning(f"Ticket {ticket_number} not found in ServiceNow")
                return
            
            current_status = status_result.get("state", "")
            current_assigned_to = status_result.get("assigned_to", "") or ""
            current_assignment_group = status_result.get("assignment_group", "") or ""
            
            previous_status = ticket_data.get("status")
            previous_assigned_to = ticket_data.get("assigned_to") or ""
            
            # Update tracking data in DB if changed
            has_changes = False
            
            if current_status != previous_status:
                logger.info(f"Status change for {ticket_number}: {previous_status} -> {current_status}")
                
                add_history({
                    "ticket_sys_id": sys_id,
                    "ticket_number": ticket_number,
                    "action": "STATUS_CHANGE",
                    "previous_status": previous_status,
                    "new_status": current_status,
                    "changed_by": "ServiceNow Sync",
                    "details": {
                        "old_status_name": self.status_mappings.get(previous_status),
                        "new_status_name": self.status_mappings.get(current_status)
                    }
                })
                
                ticket_data['status'] = current_status
                has_changes = True

                # Send notifications
                if current_status in self.closed_states:
                     # Check if previous was not closed to avoid duplicate notifications
                     if previous_status not in self.closed_states:
                        await self._send_closure_notification(sys_id, ticket_data, status_result)
                
                elif self.config.get_setting("send_status_updates", False):
                     # Send update notification
                     previous_status_name = self.status_mappings.get(previous_status, "Unknown")
                     await self._send_status_update_notification(
                         sys_id, ticket_data, status_result,
                         previous_status, previous_status_name
                     )

            # Handle possible None/Empty values for comparison
            # In DB they might be None, so we treat None as ""
            curr_assign = str(current_assigned_to) if current_assigned_to else ""
            prev_assign = str(previous_assigned_to) if previous_assigned_to else ""

            if curr_assign != prev_assign:
                 logger.info(f"Assignment change for {ticket_number}: {prev_assign} -> {curr_assign}")
                 add_history({
                    "ticket_sys_id": sys_id,
                    "ticket_number": ticket_number,
                    "action": "ASSIGNMENT_CHANGE",
                    "previous_status": previous_status,
                    "new_status": current_status,
                    "changed_by": "ServiceNow Sync",
                    "details": {
                        "old_assigned_to": prev_assign,
                        "new_assigned_to": curr_assign,
                        "assignment_group": current_assignment_group
                    }
                })
                 ticket_data['assigned_to'] = current_assigned_to
                 ticket_data['assignment_group'] = current_assignment_group
                 has_changes = True

            if has_changes:
                save_ticket(ticket_data)
                
        except Exception as e:
            logger.error(f"Error checking single ticket {sys_id}: {e}")

    async def _send_closure_notification(self, sys_id: str, ticket_data: Dict[str, Any], 
                                       status_result: Dict[str, Any]):
        """Send closure notification email"""
        try:
            ticket_number = ticket_data.get("ticket_number", "")
            caller_email = ticket_data.get("caller_email", "")
            # Reuse DB data
            short_description = ticket_data.get("short_description", "Support Request")
            
            if not caller_email:
                logger.warning(f"No caller email for ticket {ticket_number}, skipping closure notification")
                return
            
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
                
                 # Log notification in history
                add_history({
                    "ticket_sys_id": sys_id,
                    "ticket_number": ticket_number,
                    "action": "NOTIFICATION_SENT",
                    "previous_status": ticket_data.get("status"),
                    "new_status": ticket_data.get("status"),
                    "changed_by": "System",
                    "details": {"type": "CLOSURE_EMAIL", "recipient": caller_email}
                })

            else:
                logger.error(f"Failed to send closure notification for {ticket_number}: {result.get('error')}")
            
            # Sync to Jira if it was technical
            await self._sync_to_jira(ticket_number, "Done")
                
        except Exception as e:
            logger.error(f"Error sending closure notification for {sys_id}: {e}")

    async def _sync_to_jira(self, ticket_number: str, jira_status: str):
        """Sync ServiceNow status change to linked Jira issue"""
        try:
            jira_sync_url = "http://127.0.0.1:8000/jira/sync-servicenow-status"
            payload = {
                "servicenow_id": ticket_number,
                "status": jira_status
            }
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(jira_sync_url, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"Successfully synced {ticket_number} status to Jira as {jira_status}")
                    else:
                        logger.warning(f"Failed to sync {ticket_number} status to Jira. Status: {response.status}")
        except Exception as e:
            logger.error(f"Error syncing to Jira: {e}")
    
    async def _send_status_update_notification(self, sys_id: str, ticket_data: Dict[str, Any], 
                                         status_result: Dict[str, Any], 
                                         previous_status: str, previous_status_name: str):
        """Send status update notification email"""
        try:
            ticket_number = ticket_data.get("ticket_number", "")
            caller_email = ticket_data.get("caller_email", "")
            short_description = ticket_data.get("short_description", "Support Request")
            
            if not caller_email:
                logger.warning(f"No caller email for ticket {ticket_number}, skipping update notification")
                return
            
            current_status = status_result.get("state", "")
            status_name = self.status_mappings.get(current_status, "Unknown")
            
            # Create update notes
            update_notes = f"Ticket status changed to {status_name}"
            
            # Add resolution notes if available
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
                
                # Log notification in history
                add_history({
                    "ticket_sys_id": sys_id,
                    "ticket_number": ticket_number,
                    "action": "NOTIFICATION_SENT",
                    "previous_status": ticket_data.get("status"),
                    "new_status": ticket_data.get("status"),
                    "changed_by": "System",
                    "details": {"type": "STATUS_UPDATE_EMAIL", "recipient": caller_email}
                })
            else:
                logger.error(f"Failed to send status update for {ticket_number}: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Error sending status update notification for {sys_id}: {e}")
  
    def get_tracked_tickets_summary(self) -> Dict[str, Any]:
        """Get summary of currently tracked tickets from DB"""
        try:
            tickets = get_all_tickets()
            summary = {
                "total_tracked": len(tickets),
                "by_status": {},
                "pending_notifications": 0,
                "oldest_ticket": None,
                "newest_ticket": None
            }
            
            if not tickets:
                return summary
            
            oldest_time = None
            newest_time = None
            
            for ticket in tickets:
                ticket_dict = dict(ticket)
                # Count by status
                status = ticket_dict.get("status", "Unknown")
                status_name = self.status_mappings.get(status, "Unknown")
                summary["by_status"][status_name] = summary["by_status"].get(status_name, 0) + 1
                
                # timestamps
                created_str = ticket_dict.get("created_at")
                created_time = datetime.now()
                if isinstance(created_str, str):
                    try:
                        created_time = datetime.fromisoformat(created_str)
                    except ValueError:
                         pass
                elif isinstance(created_str, datetime):
                    created_time = created_str

                if oldest_time is None or created_time < oldest_time:
                    oldest_time = created_time
                    summary["oldest_ticket"] = {
                        "ticket_number": ticket_dict.get("ticket_number"),
                        "created": created_time.isoformat(),
                        "caller": ticket_dict.get("caller_email")
                    }
                
                if newest_time is None or created_time > newest_time:
                    newest_time = created_time
                    summary["newest_ticket"] = {
                        "ticket_number": ticket_dict.get("ticket_number"),
                        "created": created_time.isoformat(),
                        "caller": ticket_dict.get("caller_email")
                    }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting tracked tickets summary: {e}")
            return {"error": str(e)}
    
    def stop_tracking_ticket(self, sys_id: str) -> bool:
        """
        Stop tracking a specific ticket
        """
        # For compatibility with workflow, we just return true.
        # DB keeps the record.
        return True

    def get_ticket_status_history(self, sys_id: str) -> List[Dict[str, Any]]:
        """Get status history for a tracked ticket from DB"""
        try:
            history = get_ticket_history(sys_id)
            return history
        except Exception as e:
            logger.error(f"Error getting status history for {sys_id}: {e}")
            return []
    
    def cleanup_old_tickets(self, days_old: int = 30):
        """
        Clean up tracking data for very old tickets
        """
        # Implement DB cleanup if needed, for now skip to avoid data loss
        pass

    def force_check_ticket(self, sys_id: str) -> Dict[str, Any]:
        """
        Force an immediate status check for a specific ticket
        """
        try:
            ticket = get_ticket(sys_id)
            if not ticket:
                return {"success": False, "error": "Ticket not found in DB"}
            
            ticket_data = dict(ticket)
            
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
        """Export current tracking data"""
        return {"message": "Use DB backup instead"}

    def import_tracking_data(self, import_data: Dict[str, Any]) -> Dict[str, Any]:
        """Import tracking data"""
        return {"message": "Not supported with DB backend yet"}