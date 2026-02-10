"""
Jira Agent - Automatically creates Jira tickets for technical issues
"""

import logging
import json
import aiohttp
from typing import Dict, Any

from agents.technical_detector import TechnicalDetectorAgent
from utils.logger import setup_logger

logger = setup_logger(__name__)

class JiraAgent:
    """Agent responsible for creating Jira tickets for technical issues"""
    
    def __init__(self, config):
        self.config = config
        self.jira_endpoint = "http://127.0.0.1:8000/jira/auto-assign"
        self.technical_detector = TechnicalDetectorAgent(config)
        
    async def create_jira_ticket(self, ticket_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a Jira ticket for technical issues
        
        Args:
            ticket_data: Dictionary containing ticket information
            
        Returns:
            Dict: Result of the Jira ticket creation
        """
        try:
            # Check if the ticket is technical using the dedicated detector
            print("Checking if technical ticket")
            technical_result = await self.technical_detector.is_technical_ticket(ticket_data)
            
            if not technical_result.get("is_technical", False):
                logger.info(f"Ticket is not technical, skipping Jira creation")
                return {
                    "success": False,
                    "message": "Ticket is not technical"
                }
            
            # Generate summary and description
            summary, description = self._generate_summary_description(ticket_data)
            
            # Prepare payload
            payload = {
                "summary": summary,
                "description": description
            }
            
            # Make API call to Jira endpoint
            async with aiohttp.ClientSession() as session:
                async with session.post(self.jira_endpoint, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Successfully created Jira ticket: {summary}")
                        return {
                            "success": True,
                            "jira_ticket": result,
                            "message": "Jira ticket created successfully"
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to create Jira ticket. Status: {response.status}, Error: {error_text}")
                        return {
                            "success": False,
                            "message": f"Failed to create Jira ticket: {error_text}"
                        }
                        
        except Exception as e:
            logger.error(f"Error creating Jira ticket: {e}")
            return {
                "success": False,
                "message": f"Error creating Jira ticket: {str(e)}"
            }
    

        
    def _generate_summary_description(self, ticket_data: Dict[str, Any]) -> tuple:
        """
        Generate summary and description for Jira ticket
        
        Args:
            ticket_data: Dictionary containing ticket information
            
        Returns:
            tuple: (summary, description)
        """
        # Get data from ticket
        email_data = ticket_data.get("email", {})
        summary_data = ticket_data.get("summary", {})
        category_data = ticket_data.get("category", {})
        
        # Get ServiceNow ticket ID directly from ticket_data
        # The ticket_number is stored at the top level of ticket_data after ServiceNow creates the ticket
        servicenow_ticket_id = ticket_data.get("ticket_number", "")
        
        # Use existing summary if available, otherwise use email subject
        base_summary = summary_data.get("short_description") or email_data.get("subject", "Technical Issue")
        
        # Include ServiceNow ticket ID in the summary if available
        summary = f"[{servicenow_ticket_id}] {base_summary}" if servicenow_ticket_id else base_summary
        
        # Build description
        description_parts = []
        
        # Add summary description if available
        if summary_data.get("description"):
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
            description_parts.append("Email Content:")
            description_parts.append(email_data["body_preview"])
        
        # Add categorization info
        if category_data:
            description_parts.append("")
            description_parts.append("Categorization:")
            description_parts.append(f"Category: {category_data.get('category', 'General')}")
            if category_data.get("subcategory"):
                description_parts.append(f"Subcategory: {category_data.get('subcategory')}")
            if category_data.get("priority"):
                description_parts.append(f"Priority: {category_data.get('priority')}")
        
        # Join all parts with newlines
        description = "\n".join(description_parts)
        
        return summary, description