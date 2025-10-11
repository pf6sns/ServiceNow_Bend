"""
ServiceNow API Helper - REST API interactions with ServiceNow
"""

import logging
import httpx
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import base64
import requests
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ServiceNowAPI:
    """Helper class for ServiceNow REST API interactions"""
    
    def __init__(self, config):
        self.config = config
        
        # ServiceNow configuration
        self.instance_url = self.config.get_secret("SERVICENOW_INSTANCE_URL")
        self.username = self.config.get_secret("SERVICENOW_USERNAME")
        self.password = self.config.get_secret("SERVICENOW_PASSWORD")
        
        # Ensure instance URL format
        if not self.instance_url.startswith('https://'):
            self.instance_url = f"https://{self.instance_url}"
        if not self.instance_url.endswith('/'):
            self.instance_url += '/'
        
        # API endpoints
        self.api_base = f"{self.instance_url}api/now/table/"
        
        # HTTP client configuration
        self.timeout = 30
        
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        auth_string = f"{self.username}:{self.password}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        return {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Internal helper for making REST API requests
        """
        # Remove any leading slashes from endpoint to avoid double slashes
        endpoint = endpoint.lstrip('/')
        
        # Ensure we don't have double slashes in the URL
        url = f"{self.api_base}{endpoint}"
        logger.debug(f"Making {method} request to: {url}")
        
        try:
            response = requests.request(
                method,
                url,
                auth=(self.username, self.password),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}

    # In servicenow_api.py, make sure the create_incident method is working correctly

    def create_incident(self, incident_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new incident in ServiceNow
        
        Args:
            incident_data: Incident data dictionary
            
        Returns:
            Dict containing creation result with sys_id and number
        """
        try:
            logger.info("Creating incident in ServiceNow")
            logger.debug(f"Incident data: {json.dumps(incident_data, indent=2)}")
            
            result = self._make_request("POST", "incident", data=incident_data)
            
            if result.get("success"):
                response_data = result.get("data", {}).get("result", {})
                
                # Extract assignment information
                assignment_group = response_data.get("assignment_group", {})
                if isinstance(assignment_group, dict):
                    assignment_group_value = assignment_group.get("value", "")
                    assignment_group_display = assignment_group.get("display_value", "")
                else:
                    assignment_group_value = assignment_group
                    assignment_group_display = assignment_group
                
                assigned_to = response_data.get("assigned_to", {})
                if isinstance(assigned_to, dict):
                    assigned_to_value = assigned_to.get("value", "")
                    assigned_to_display = assigned_to.get("display_value", "")
                else:
                    assigned_to_value = assigned_to
                    assigned_to_display = assigned_to
                
                logger.info(f"Incident created successfully: {response_data.get('number')}")
                logger.info(f"Assignment Group: {assignment_group_display} ({assignment_group_value})")
                logger.info(f"Assigned To: {assigned_to_display} ({assigned_to_value})")
                
                return {
                    "success": True,
                    "sys_id": response_data.get("sys_id"),
                    "ticket_number": response_data.get("number"),
                    "state": response_data.get("state"),
                    "assigned_to": assigned_to_display,
                    "assignment_group": assignment_group_display
                }
            else:
                logger.error(f"Failed to create incident: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error creating incident: {e}")
            return {"success": False, "error": str(e)}

    def get_incident(self, sys_id: str) -> Dict[str, Any]:
        """
        Get incident details by sys_id
        
        Args:
            sys_id: ServiceNow sys_id of the incident
            
        Returns:
            Dict containing incident data
            
        """
        def safe_display(field: Any) -> str:
            if isinstance(field, dict):
                return field.get("display_value", "")
            elif field:  # non-empty string or number
                return str(field)
            return ""
        try:
            result = self._make_request("GET", f"incident/{sys_id}")
           
            if result.get("success"):
                incident_data = result.get("data", {}).get("result", {})
                
                if incident_data:
                    return {
                        "found": True,
                        "sys_id": incident_data.get("sys_id"),
                        "number": incident_data.get("number"),
                        "state": incident_data.get("state"),
                        "state_name": safe_display(incident_data.get("state")),
                        "short_description": incident_data.get("short_description"),
                        "description": incident_data.get("description"),
                        "caller_id": safe_display(incident_data.get("caller_id")),
                        "assigned_to": safe_display(incident_data.get("assigned_to")),
                        "assignment_group": safe_display(incident_data.get("assignment_group")),
                        "priority": incident_data.get("priority"),
                        "urgency": incident_data.get("urgency"),
                        "category": incident_data.get("category"),
                        "subcategory": incident_data.get("subcategory"),
                        "resolution_code": incident_data.get("resolution_code"),
                        "resolution_notes": incident_data.get("resolution_notes"),
                        "sys_created_on": incident_data.get("sys_created_on"),
                        "sys_updated_on": incident_data.get("sys_updated_on")
                    }

                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error getting incident {sys_id}: {e}")
            return {"found": False, "error": str(e)}
    
    def update_incident(self, sys_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing incident
        
        Args:
            sys_id: ServiceNow sys_id of the incident
            update_data: Data to update
            
        Returns:
            Dict containing update result
        """
        try:
            result = self._make_request("PUT", f"incident/{sys_id}", data=update_data)
            
            if result.get("success"):
                return {"success": True, "message": "Incident updated successfully"}
            else:
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error updating incident {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def add_comment(self, sys_id: str, comment: str, comment_type: str = "work_notes") -> Dict[str, Any]:
        """
        Add comment or work note to incident
        
        Args:
            sys_id: ServiceNow sys_id of the incident
            comment: Comment text
            comment_type: Type of comment ('work_notes' or 'comments')
            
        Returns:
            Dict containing result
        """
        try:
            update_data = {comment_type: comment}
            return self.update_incident(sys_id, update_data)
            
        except Exception as e:
            logger.error(f"Error adding comment to {sys_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def lookup_user_by_email(self, email: str) -> Dict[str, Any]:
        """
        Lookup user by email address
        
        Args:
            email: Email address to search for
            
        Returns:
            Dict containing user information
        """
        try:
            params = {
                "sysparm_query": f"email={email}",
                "sysparm_limit": "1"
            }
            
            result = self._make_request("GET", "sys_user", params=params)
            
            if result.get("success"):
                users = result.get("data", {}).get("result", [])
                if users:
                    user = users[0]
                    return {
                        "found": True,
                        "sys_id": user.get("sys_id"),
                        "name": user.get("name"),
                        "email": user.get("email"),
                        "user_name": user.get("user_name"),
                        "active": user.get("active") == "true"
                    }
                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error looking up user by email {email}: {e}")
            return {"found": False, "error": str(e)}
    
    def lookup_user_by_username(self, username: str) -> Dict[str, Any]:
        """
        Lookup user by username
        
        Args:
            username: Username to search for
            
        Returns:
            Dict containing user information
        """
        try:
            params = {
                "sysparm_query": f"user_name={username}",
                "sysparm_limit": "1"
            }
            
            result = self._make_request("GET", "sys_user", params=params)
            
            if result.get("success"):
                users = result.get("data", {}).get("result", [])
                if users:
                    user = users[0]
                    return {
                        "found": True,
                        "sys_id": user.get("sys_id"),
                        "name": user.get("name"),
                        "email": user.get("email"),
                        "user_name": user.get("user_name"),
                        "active": user.get("active") == "true"
                    }
                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error looking up user by username {username}: {e}")
            return {"found": False, "error": str(e)}
    
    def lookup_user_by_sys_id(self, sys_id: str) -> Dict[str, Any]:
        """
        Lookup user by sys_id
        
        Args:
            sys_id: ServiceNow sys_id of the user
            
        Returns:
            Dict containing user information
        """
        try:
            result = self._make_request("GET", f"sys_user/{sys_id}")
            
            if result.get("success"):
                user = result.get("data", {}).get("result", {})
                if user:
                    return {
                        "found": True,
                        "sys_id": user.get("sys_id"),
                        "name": user.get("name"),
                        "email": user.get("email"),
                        "user_name": user.get("user_name"),
                        "active": user.get("active") == "true"
                    }
                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error looking up user by sys_id {sys_id}: {e}")
            return {"found": False, "error": str(e)}
    
    def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new user in ServiceNow
        
        Args:
            user_data: User data dictionary
            
        Returns:
            Dict containing creation result
        """
        try:
            result = self._make_request("POST", "sys_user", data=user_data)
            
            if result.get("success"):
                user_result = result.get("data", {}).get("result", {})
                return {
                    "success": True,
                    "sys_id": user_result.get("sys_id"),
                    "name": user_result.get("name"),
                    "user_name": user_result.get("user_name"),
                    "email": user_result.get("email")
                }
            else:
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return {"success": False, "error": str(e)}
    # Add this method to the ServiceNowAPI class in servicenow_api.py

    def get_group_members(self, group_sys_id: str, limit: int = 50) -> Dict[str, Any]:
        """
        Get users from a specific group
        
        Args:
            group_sys_id: ServiceNow sys_id of the group
            limit: Maximum number of users to return
            
        Returns:
            Dict containing group members information
        """
        try:
            params = {
                "sysparm_query": f"group={group_sys_id}",
                "sysparm_fields": "user.name,user.email,user.user_name,user.sys_id",
                "sysparm_limit": str(limit)
            }
            
            logger.debug(f"Getting members for group: {group_sys_id}")
            result = self._make_request("GET", "sys_user_grmember", params=params)
            
            if result.get("success"):
                members_data = result.get("data", {}).get("result", [])
                logger.debug(f"Found {len(members_data)} members in group {group_sys_id}")
                
                # Format the response to extract user information
                formatted_members = []
                for member in members_data:
                    formatted_members.append({
                        "sys_id": member.get("user.sys_id", ""),
                        "email": member.get("user.email", ""),
                        "name": member.get("user.name", ""),
                        "user_name": member.get("user.user_name", "")
                    })
                
                return {
                    "success": True,
                    "members": formatted_members,
                    "total_members": len(formatted_members)
                }
            else:
                logger.error(f"Error getting group members: {result.get('error')}")
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error getting group members for {group_sys_id}: {e}")
            return {"success": False, "error": str(e)}    
    def get_group_by_sys_id(self, group_sys_id: str) -> Dict[str, Any]:
        """
        Get group details by sys_id
        
        Args:
            group_sys_id: ServiceNow sys_id of the group
            
        Returns:
            Dict containing group information
        """
        try:
            result = self._make_request("GET", f"sys_user_group/{group_sys_id}")
            
            if result.get("success"):
                group_data = result.get("data", {}).get("result", {})
                if group_data:
                    return {
                        "found": True,
                        "sys_id": group_data.get("sys_id"),
                        "name": group_data.get("name"),
                        "description": group_data.get("description", ""),
                        "active": group_data.get("active") == "true"
                    }
                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error getting group by sys_id {group_sys_id}: {e}")
            return {"found": False, "error": str(e)}
    def lookup_group_by_name(self, group_name: str) -> Dict[str, Any]:
        """
        Lookup assignment group by name
        
        Args:
            group_name: Group name to search for
            
        Returns:
            Dict containing group information
        """
        try:
            params = {
                "sysparm_query": f"name={group_name}",
                "sysparm_limit": "1"
            }
            
            result = self._make_request("GET", "sys_user_group", params=params)
            
            if result.get("success"):
                groups = result.get("data", {}).get("result", [])
                if groups:
                    group = groups[0]
                    return {
                        "found": True,
                        "sys_id": group.get("sys_id"),
                        "name": group.get("name"),
                        "description": group.get("description"),
                        "active": group.get("active") == "true"
                    }
                else:
                    return {"found": False}
            else:
                return {"found": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error looking up group {group_name}: {e}")
            return {"found": False, "error": str(e)}
    
    def search_incidents_by_caller_email(self, email: str, days_back: int = 30) -> Dict[str, Any]:
        """
        Search for incidents by caller email
        
        Args:
            email: Caller email address
            days_back: Number of days to search back
            
        Returns:
            Dict containing search results
        """
        try:
            # First lookup user by email
            user_result = self.lookup_user_by_email(email)
            
            if not user_result.get("found"):
                return {"success": True, "incidents": []}
            
            user_sys_id = user_result.get("sys_id")
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            params = {
                "sysparm_query": f"caller_id={user_sys_id}^sys_created_on>={start_date.strftime('%Y-%m-%d')}",
                "sysparm_limit": "100",
                "sysparm_order": "sys_created_on"
            }
            
            result = self._make_request("GET", "incident", params=params)
            
            if result.get("success"):
                incidents = result.get("data", {}).get("result", [])
                formatted_incidents = []
                
                for incident in incidents:
                    formatted_incidents.append({
                        "sys_id": incident.get("sys_id"),
                        "number": incident.get("number"),
                        "short_description": incident.get("short_description"),
                        "state": incident.get("state"),
                        "state_name": incident.get("state", {}).get("display_value", ""),
                        "priority": incident.get("priority"),
                        "created_on": incident.get("sys_created_on"),
                        "updated_on": incident.get("sys_updated_on")
                    })
                
                return {"success": True, "incidents": formatted_incidents}
            else:
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error searching incidents for {email}: {e}")
            return {"success": False, "error": str(e)}
    
    def get_incident_categories(self) -> Dict[str, Any]:
        """
        Get available incident categories from ServiceNow
        
        Returns:
            Dict containing categories
        """
        try:
            # This would typically query a category table or choice list
            # For now, return common categories
            categories = {
                "Software": "Software related issues",
                "Hardware": "Hardware related issues", 
                "Network": "Network and connectivity issues",
                "Security": "Security related issues",
                "Database": "Database issues",
                "Inquiry / Help": "General inquiries and help requests"
            }
            
            return {"success": True, "categories": categories}
            
        except Exception as e:
            logger.error(f"Error getting incident categories: {e}")
            return {"success": False, "error": str(e)}
    
    def test_connection(self) -> bool:
        """
        Test connection to ServiceNow instance
        
        Returns:
            bool: True if connection successful
        """
        try:
            params = {"sysparm_limit": "1"}
            result = self._make_request("GET", "incident", params=params)
            
            if result.get("success"):
                logger.info("ServiceNow connection test successful")
                return True
            else:
                logger.error(f"ServiceNow connection test failed: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"ServiceNow connection test error: {e}")
            return False
    
    def get_incident_states(self) -> Dict[str, str]:
        """
        Get incident state mappings
        
        Returns:
            Dict mapping state values to names
        """
        return {
            "1": "New",
            "2": "In Progress",
            "3": "On Hold", 
            "6": "Resolved",
            "7": "Closed",
            "8": "Canceled"
        }
    
    def search_incidents(self, query_params: Dict[str, str], limit: int = 100) -> Dict[str, Any]:
        """
        Generic incident search
        
        Args:
            query_params: Query parameters for search
            limit: Maximum number of results
            
        Returns:
            Dict containing search results
        """
        try:
            params = {
                "sysparm_limit": str(limit),
                **query_params
            }
            
            result = self._make_request("GET", "incident", params=params)
            
            if result.get("success"):
                incidents = result.get("data", {}).get("result", [])
                return {"success": True, "incidents": incidents, "count": len(incidents)}
            else:
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error searching incidents: {e}")
            return {"success": False, "error": str(e)}
    
    def get_assignment_groups(self, active_only: bool = True) -> Dict[str, Any]:
        """
        Get list of assignment groups
        
        Args:
            active_only: Only return active groups
            
        Returns:
            Dict containing groups list
        """
        try:
            params = {"sysparm_limit": "1000"}
            
            if active_only:
                params["sysparm_query"] = "active=true"
            
            result = self._make_request("GET", "sys_user_group", params=params)
            
            if result.get("success"):
                groups = result.get("data", {}).get("result", [])
                formatted_groups = []
                
                for group in groups:
                    formatted_groups.append({
                        "sys_id": group.get("sys_id"),
                        "name": group.get("name"),
                        "description": group.get("description", ""),
                        "active": group.get("active") == "true"
                    })
                
                return {"success": True, "groups": formatted_groups}
            else:
                return {"success": False, "error": result.get("error")}
                
        except Exception as e:
            logger.error(f"Error getting assignment groups: {e}")
            return {"success": False, "error": str(e)}