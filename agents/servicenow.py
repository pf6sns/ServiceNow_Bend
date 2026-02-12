"""
ServiceNow Agent - Creates incidents in ServiceNow using REST API
Handles dynamic user/group lookups with fallback to config defaults
"""

import logging
from typing import Dict, Any, Optional, List
import httpx
import json
from datetime import datetime
import random

from tools.servicenow_api import ServiceNowAPI
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ServiceNowAgent:
    """Agent responsible for creating and managing ServiceNow incidents"""
    
    def __init__(self, config):
        self.config = config
        
        # Initialize ServiceNow API helper
        self.servicenow_api = ServiceNowAPI(config)
        
        # Cache for user and group lookups
        self._user_cache = {}
        self._group_cache = {}
        self._category_cache = {}
        self._group_members_cache = {}
        
        # Get fallback assignments from config
        self.fallback_config = config.get_setting("servicenow_fallbacks", {})
    
    def create_incident(self, ticket_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an incident in ServiceNow with improved assignment logic"""
        try:
            email_data = ticket_data.get("email", {})
            summary_data = ticket_data.get("summary", {})
            category_data = ticket_data.get("category", {})
            
            # 1. DE-DUPLICATION CHECK
            message_id = email_data.get("message_id")
            if message_id:
                # Check if incident with this correlation_id already exists
                existing = self._check_duplicate_by_correlation_id(message_id)
                if existing:
                    logger.info(f"DUPLICATE DETECTED: Ticket {existing['number']} already exists for email {message_id}")
                    return {
                        "success": True,
                        "ticket_number": existing.get("number"),
                        "sys_id": existing.get("sys_id"),
                        "already_exists": True
                    }

            logger.info(f"Creating ServiceNow incident for {email_data.get('from', 'unknown')}")
            
            # Lookup caller information
            caller_info = self._lookup_caller(email_data.get("from", ""))
            logger.info(f"Caller lookup result: {caller_info}")
            
            # Lookup assignment group
            assignment_group = self._lookup_assignment_group(category_data.get("category", "General"))
            logger.info(f"Assignment group lookup result: {assignment_group}")
            
            # Lookup assigned user from the group
            assigned_user = {"sys_id": "", "name": ""}
            if assignment_group.get("sys_id"):
                assigned_user = self._get_user_from_assignment_group(assignment_group.get("sys_id"))
                logger.info(f"Assigned user lookup result: {assigned_user}")
            
            # Prepare incident data with validation
            incident_data = {
                "short_description": ticket_data.get("short_description", "Support Request")[:160],
                "description": self._build_incident_description(ticket_data),
                "contact_type": "email",
                "priority": str(category_data.get("priority", 3)),
                "urgency": str(category_data.get("urgency", 3)),
                "category": self._map_category_to_servicenow(category_data.get("category", "inquiry")),
                "correlation_id": message_id # Use message_id for de-duplication
            }
            
            # Add caller only if found
            if caller_info.get("sys_id"):
                incident_data["caller_id"] = caller_info["sys_id"]
            
            # Add assignment group only if found
            if assignment_group.get("sys_id"):
                incident_data["assignment_group"] = assignment_group["sys_id"]
            
            # Add assigned user only if found
            if assigned_user.get("sys_id"):
                incident_data["assigned_to"] = assigned_user["sys_id"]
            
            logger.info(f"Final incident data: {json.dumps(incident_data, indent=2)}")
            
            # Create incident via API
            result = self.servicenow_api.create_incident(incident_data)
            
            if result.get("success"):
                logger.info(f"Successfully created incident: {result.get('ticket_number')}")
                logger.info(f"Assigned to group: {assignment_group.get('name', 'None')}")
                logger.info(f"Assigned to user: {assigned_user.get('name', 'None')}")
                
                return {
                    "success": True,
                    "ticket_number": result.get("ticket_number"),
                    "sys_id": result.get("sys_id"),
                    "assignment_group": assignment_group.get("name", ""),
                    "assigned_user": assigned_user.get("name", ""),
                    "caller": caller_info.get("name", "")
                }
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"Failed to create incident: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg
                }
                
        except Exception as e:
            logger.error(f"Error creating ServiceNow incident: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _check_duplicate_by_correlation_id(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """Check if an incident with the given correlation_id already exists"""
        try:
            params = {
                "sysparm_query": f"correlation_id={correlation_id}",
                "sysparm_limit": "1",
                "sysparm_fields": "sys_id,number"
            }
            result = self.servicenow_api._make_request("GET", "incident", params=params)
            
            if result.get("success"):
                incidents = result.get("data", {}).get("result", [])
                if incidents:
                    return incidents[0]
            return None
        except Exception as e:
            logger.error(f"Error checking duplicate correlation_id: {e}")
            return None
    def _get_user_from_assignment_group(self, group_sys_id: str) -> Dict[str, Any]:
        """Get a user from the assignment group for ticket assignment"""
        if not group_sys_id:
            logger.warning("No group sys_id provided")
            return {"sys_id": "", "name": ""}
        
        try:
            # Check cache first
            cache_key = f"group_members_{group_sys_id}"
            if cache_key in self._group_members_cache:
                members = self._group_members_cache[cache_key]
                logger.info(f"Using cached members for group {group_sys_id}: {len(members)} members")
            else:
                # Get group members from ServiceNow
                members_result = self.servicenow_api.get_group_members(group_sys_id)
                logger.info(f"Group members API result: {members_result}")
                
                if members_result.get("success") and members_result.get("members"):
                    members = members_result["members"]
                    self._group_members_cache[cache_key] = members
                    logger.info(f"Found {len(members)} members in group {group_sys_id}")
                else:
                    logger.warning(f"No members found for group {group_sys_id}")
                    return {"sys_id": "", "name": ""}
            
            # Select a random user from the group for load balancing
            if members:
                selected_user = random.choice(members)
                logger.info(f"Selected user {selected_user.get('name')} from group")
                return {
                    "sys_id": selected_user.get("sys_id", ""),
                    "name": selected_user.get("name", ""),
                    "email": selected_user.get("email", "")
                }
            else:
                logger.warning(f"No active members in group {group_sys_id}")
                return {"sys_id": "", "name": ""}
                
        except Exception as e:
            logger.error(f"Error getting user from assignment group {group_sys_id}: {e}")
            return {"sys_id": "", "name": ""}

    def _build_incident_description(self, ticket_data: Dict[str, Any]) -> str:
        """Build detailed incident description"""
        email_data = ticket_data.get("email", {})
        summary_data = ticket_data.get("summary", {})
        category_data = ticket_data.get("category", {})
        
        description_parts = []
        
        # Add summary description
        if summary_data.get("description"):
            description_parts.append("Issue Description:")
            description_parts.append(summary_data["description"])
            description_parts.append("")
        
        # Add email details
        description_parts.append("Email Details:")
        description_parts.append(f"From: {email_data.get('from', 'Unknown')}")
        description_parts.append(f"Subject: {email_data.get('subject', 'No Subject')}")
        description_parts.append(f"Date: {email_data.get('date', 'Unknown')}")
        
        # Add body preview if available
        if email_data.get("body_preview"):
            description_parts.append("")
            description_parts.append("Email Preview:")
            description_parts.append(email_data["body_preview"])
        
        # Add categorization info
        if category_data.get("reasoning"):
            description_parts.append("")
            description_parts.append("Categorization:")
            description_parts.append(f"Category: {category_data.get('category', 'General')}")
            description_parts.append(f"Reasoning: {category_data.get('reasoning', '')}")
        
        # Add timestamp
        description_parts.append("")
        description_parts.append(f"Auto-generated: {datetime.now().isoformat()}")
        
        return "\n".join(description_parts)
    
    def _lookup_caller(self, email_address: str) -> Dict[str, Any]:
        """Lookup caller information by email address"""
        if not email_address:
            return self._get_fallback_caller()
        
        # Check cache first
        if email_address in self._user_cache:
            return self._user_cache[email_address]
        
        try:
            # Lookup user in ServiceNow
            user_result = self.servicenow_api.lookup_user_by_email(email_address)
            
            if user_result.get("found"):
                caller_info = {
                    "sys_id": user_result.get("sys_id"),
                    "name": user_result.get("name"),
                    "email": email_address
                }
                # Cache result
                self._user_cache[email_address] = caller_info
                logger.debug(f"Found caller: {caller_info['name']}")
                return caller_info
            else:
                # Create new user or use fallback
                return self._handle_unknown_caller(email_address)
                
        except Exception as e:
            logger.error(f"Error looking up caller {email_address}: {e}")
            return self._get_fallback_caller()
    
    def _handle_unknown_caller(self, email_address: str) -> Dict[str, Any]:
        """Handle unknown caller - create user or use fallback"""
        try:
            # Try to create new user
            if self.config.get_setting("create_unknown_users", False):
                user_data = {
                    "email": email_address,
                    "user_name": email_address.split("@")[0],
                    "first_name": email_address.split("@")[0],
                    "last_name": "External",
                    "active": True
                }
                
                result = self.servicenow_api.create_user(user_data)
                if result.get("success"):
                    caller_info = {
                        "sys_id": result.get("sys_id"),
                        "name": result.get("name"),
                        "email": email_address
                    }
                    self._user_cache[email_address] = caller_info
                    logger.info(f"Created new user: {email_address}")
                    return caller_info
            
            # Fallback to default caller
            return self._get_fallback_caller()
            
        except Exception as e:
            logger.error(f"Error handling unknown caller: {e}")
            return self._get_fallback_caller()
    
    def _get_fallback_caller(self) -> Dict[str, Any]:
        """Get fallback caller from config"""
        fallback_user = self.fallback_config.get("default_caller", {})
        
        if not fallback_user:
            # Hardcoded fallback
            return {
                "sys_id": "",
                "name": "Unknown Caller",
                "email": "unknown@company.com"
            }
        
        return {
            "sys_id": fallback_user.get("sys_id", ""),
            "name": fallback_user.get("name", "Default Caller"),
            "email": fallback_user.get("email", "default@company.com")
        }
    
    def _lookup_assignment_group(self, category: str) -> Dict[str, Any]:
        """Lookup assignment group based on category"""
        cache_key = f"group_{category}"
        
        # Check cache
        if cache_key in self._group_cache:
            return self._group_cache[cache_key]
        
        try:
            # Get group mapping from config
            group_mappings = self.config.get_setting("category_to_group", {})
            mapped_group = group_mappings.get(category)
            
            if mapped_group:
                # Lookup group in ServiceNow
                result = self.servicenow_api.lookup_group_by_name(mapped_group)
                
                if result.get("found"):
                    group_info = {
                        "sys_id": result.get("sys_id"),
                        "name": result.get("name")
                    }
                    self._group_cache[cache_key] = group_info
                    logger.info(f"Found assignment group: {group_info['name']} for category: {category}")
                    return group_info
            
            # If no mapping found, try to use a real group from your ServiceNow instance
            # Based on your API response, let's use "SNS IHUB"
            fallback_group_name = "SNS IHUB"
            result = self.servicenow_api.lookup_group_by_name(fallback_group_name)
            
            if result.get("found"):
                group_info = {
                    "sys_id": result.get("sys_id"),
                    "name": result.get("name")
                }
                self._group_cache[cache_key] = group_info
                logger.info(f"Using fallback group: {group_info['name']} for category: {category}")
                return group_info
                
            # Final fallback if nothing works
            return self._get_fallback_group()
            
        except Exception as e:
            logger.error(f"Error looking up assignment group for {category}: {e}")
            return self._get_fallback_group()
        
    def _get_fallback_group(self) -> Dict[str, Any]:
        """Get fallback assignment group from config"""
        fallback_group = self.fallback_config.get("default_assignment_group", {})
        
        if fallback_group.get("sys_id"):
            return fallback_group
        
        # Use actual group from your ServiceNow instance
        return {
            "sys_id": "019ad92ec7230010393d265c95c260dd",  # SNS IHUB
            "name": "SNS IHUB"
        }

    # 3. Configuration you need to add to your config file:
    CONFIG_EXAMPLE = {
        "category_to_group": {
            "IT": "SNS IHUB",
            "General": "SNS IHUB", 
            "Support": "MIF Admins",
            # Add more mappings as needed
        },
        "servicenow_fallbacks": {
            "default_assignment_group": {
                "sys_id": "019ad92ec7230010393d265c95c260dd",
                "name": "SNS IHUB"
            },
            "default_caller": {
                "sys_id": "",  # Leave empty to create new users
                "name": "External User",
                "email": "external@company.com"
            }
        }
    }
    def _lookup_assigned_user(self, category: str) -> Dict[str, Any]:
        """Lookup assigned user based on category"""
        cache_key = f"user_{category}"
        
        # Check cache
        if cache_key in self._user_cache:
            return self._user_cache[cache_key]
        
        try:
            # Get user mapping from config
            user_mappings = self.config.get_setting("category_to_user", {})
            mapped_user = user_mappings.get(category)
            
            if mapped_user:
                # Lookup user in ServiceNow
                result = self.servicenow_api.lookup_user_by_username(mapped_user)
                
                if result.get("found"):
                    user_info = {
                        "sys_id": result.get("sys_id"),
                        "name": result.get("name")
                    }
                    self._user_cache[cache_key] = user_info
                    return user_info
            
            # No specific user assignment
            return {"sys_id": "", "name": ""}
            
        except Exception as e:
            logger.error(f"Error looking up assigned user for {category}: {e}")
            return {"sys_id": "", "name": ""}
    
    def _map_category_to_servicenow(self, category: str) -> str:
        """Map internal category to ServiceNow category values"""
        category_mappings = self.config.get_setting("servicenow_category_mapping", {})
        
        # Use mapping if available
        if category in category_mappings:
            return category_mappings[category]
        
        # Default mappings
        default_mappings = {
            "IT": "Software",
            "HR": "Human Resources",
            "Finance": "Finance",
            "Facilities": "Facilities",
            "General": "General"
        }
        
        return default_mappings.get(category, "General")
    
    def update_incident(self, sys_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update existing incident in ServiceNow"""
        try:
            result = self.servicenow_api.update_incident(sys_id, update_data)
            
            if result.get("success"):
                logger.info(f"Successfully updated incident {sys_id}")
                return {"success": True}
            else:
                logger.error(f"Failed to update incident {sys_id}: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error updating incident {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def get_incident_status(self, sys_id: str) -> Dict[str, Any]:
        """Get current status of incident"""
        try:
            result = self.servicenow_api.get_incident(sys_id)
            
            if result.get("found"):
                return {
                    "found": True,
                    "state": result.get("state"),
                    "state_name": result.get("state_name"),
                    "resolution_code": result.get("resolution_code"),
                    "resolution_notes": result.get("resolution_notes"),
                    "updated": result.get("sys_updated_on")
                }
            else:
                return {"found": False}
                
        except Exception as e:
            logger.error(f"Error getting incident status {sys_id}: {e}")
            return {"found": False, "error": str(e)}
    
    def add_comment_to_incident(self, sys_id: str, comment: str, comment_type: str = "work_notes") -> Dict[str, Any]:
        """Add comment/work note to incident"""
        try:
            result = self.servicenow_api.add_comment(sys_id, comment, comment_type)
            
            if result.get("success"):
                logger.debug(f"Added comment to incident {sys_id}")
                return {"success": True}
            else:
                logger.error(f"Failed to add comment to {sys_id}: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error adding comment to {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def close_incident(self, sys_id: str, resolution_code: str = "Closed/Resolved by Caller", 
                      resolution_notes: str = "") -> Dict[str, Any]:
        """Close an incident"""
        try:
            close_data = {
                "state": "6",  # Closed
                "resolution_code": resolution_code,
                "resolution_notes": resolution_notes,
                "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            result = self.servicenow_api.update_incident(sys_id, close_data)
            
            if result.get("success"):
                logger.info(f"Successfully closed incident {sys_id}")
                return {"success": True}
            else:
                logger.error(f"Failed to close incident {sys_id}: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error closing incident {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def search_incidents_by_email(self, email: str, days_back: int = 30) -> List[Dict[str, Any]]:
        """Search for recent incidents by caller email"""
        try:
            result = self.servicenow_api.search_incidents_by_caller_email(email, days_back)
            
            if result.get("success"):
                incidents = result.get("incidents", [])
                logger.debug(f"Found {len(incidents)} incidents for {email}")
                return incidents
            else:
                logger.error(f"Failed to search incidents for {email}: {result.get('error')}")
                return []
                
        except Exception as e:
            logger.error(f"Error searching incidents for {email}: {e}")
            return []
    
    def get_incident_metrics(self) -> Dict[str, Any]:
        """Get incident metrics and statistics"""
        try:
            # This could be expanded to get various metrics
            metrics = {
                "total_created_today": 0,
                "open_incidents": 0,
                "avg_resolution_time": 0
            }
            
            # Implement actual metrics gathering if needed
            logger.debug("Retrieved incident metrics")
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting incident metrics: {e}")
            return {}
    
    def validate_servicenow_connection(self) -> bool:
        """Validate connection to ServiceNow instance"""
        try:
            return self.servicenow_api.test_connection()
        except Exception as e:
            logger.error(f"ServiceNow connection validation failed: {e}")
            return False