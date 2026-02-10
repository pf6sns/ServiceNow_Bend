"""
Scheduler Agent - Orchestrates the entire agentic workflow using LangGraph StateGraph
Triggers every 10 minutes and coordinates all other agents
"""

import asyncio
import logging
from typing import Dict, Any, List, TypedDict
from datetime import datetime, timedelta
from langgraph.graph import StateGraph, END

from agents.mail_fetcher import MailFetcherAgent
from agents.classifier import ClassifierAgent
from agents.summary import SummaryAgent
from agents.category_extractor import CategoryExtractorAgent
from agents.servicenow import ServiceNowAgent
from agents.notification import NotificationAgent
from agents.tracker import TrackerAgent
from agents.jira_agent import JiraAgent
from utils.logger import setup_logger

logger = setup_logger(__name__)

class WorkflowState(TypedDict):
    """State definition for the workflow"""
    # Input/Output data
    emails: List[Dict[str, Any]]  # REMOVED add_messages
    support_emails: List[Dict[str, Any]]  # REMOVED add_messages
    processed_tickets: List[Dict[str, Any]]  # REMOVED add_messages
    total_emails: int
    error: str
    
    # Metadata
    timestamp: str
    last_check: str

class SchedulerAgent:
    """Main scheduler agent that orchestrates the workflow using LangGraph StateGraph"""
    
    def __init__(self, config):
        self.config = config
        self.last_check_time = datetime.now() - timedelta(minutes=1)
        
        # Initialize all agents
        self.mail_fetcher = MailFetcherAgent(config)
        self.classifier = ClassifierAgent(config)
        self.summary = SummaryAgent(config)
        self.category_extractor = CategoryExtractorAgent(config)
        self.servicenow = ServiceNowAgent(config)
        self.notification = NotificationAgent(config)
        self.tracker = TrackerAgent(config)
        self.jira_agent = JiraAgent(config)
        
        # Build the workflow graph
        self.workflow = self._build_workflow_graph()
        
    def _build_workflow_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph workflow for the agentic process"""
        
        def fetch_emails(state: WorkflowState) -> WorkflowState:
            """Node: Fetch emails from Gmail"""
            try:
                logger.info("Fetching emails from Gmail...")
                # Get the actual email objects
                raw_emails = self.mail_fetcher.fetch_unread_emails(
                    since_time=self.last_check_time
                )
                
                # Store the original email objects directly
                state["emails"] = raw_emails
                state["total_emails"] = len(raw_emails)
                logger.info(f"Fetched {len(raw_emails)} unread emails")
                return state
            except Exception as e:
                logger.error(f"Error fetching emails: {e}")
                state["error"] = str(e)
                return state
        
        def classify_emails(state: WorkflowState) -> WorkflowState:
            """Node: Classify emails as support-related or not"""
            if state.get("error") or not state.get("emails"):
                return state
                
            support_emails = []
            for email in state["emails"]:
                try:
                    # Pass the original email data to classifier
                    is_support = self.classifier.classify_email(email)
                    if is_support:
                        # Keep the original email object
                        support_emails.append(email)
                        logger.info(f"Email '{email.get('subject', 'No subject')}' classified as support-related")
                    else:
                        logger.info(f"Email '{email.get('subject', 'No subject')}' classified as non-support")
                except Exception as e:
                    logger.error(f"Error classifying email: {e}")
                    continue
            
            state["support_emails"] = support_emails
            logger.info(f"Classified {len(support_emails)} emails as support-related")
            return state
        
        def process_support_emails(state: WorkflowState) -> WorkflowState:
            """Node: Process each support email to create tickets"""
            if state.get("error") or not state.get("support_emails"):
                return state
            
            processed_tickets = []
            
            for email in state["support_emails"]:
                try:
                    # Generate summary using original email
                    summary_result = self.summary.generate_summary(email)
                    
                    # Extract category using AI + business rules (HR/Finance/Facilities/IT)
                    category_result = self.category_extractor.extract_category_with_rules(email)
                    
                    # Create ServiceNow ticket
                    ticket_data = {
                        "email": email,
                        "summary": summary_result,
                        "category": category_result,
                        "short_description": summary_result.get("short_description", "Support Request"),
                        "description": summary_result.get("description", email.get("subject", "")),
                        "caller_email": email.get("from", ""),
                        "category_name": category_result.get("category", "General"),
                        "priority": category_result.get("priority", "3"),
                        "urgency": category_result.get("urgency", "3")
                    }
                    
                    # Create ticket in ServiceNow
                    ticket_result = self.servicenow.create_incident(ticket_data)
                    print("Ticket Result:",ticket_result.get("success"))
                    
                    if ticket_result.get("success"):
                        ticket_data["ticket_number"] = ticket_result.get("ticket_number")
                        ticket_data["sys_id"] = ticket_result.get("sys_id")
                        processed_tickets.append(ticket_data)
                        
                        # Send confirmation email
                        self.notification.send_confirmation_email(
                            email.get("from", ""),
                            ticket_result.get("ticket_number"),
                            summary_result.get("short_description", "")
                        )
                        
                        logger.info(f"Created ticket {ticket_result.get('ticket_number')} for email from {email.get('from', '')}")
                        logger.info("Sending jira")
                        # Check if technical ticket and create Jira ticket if needed
                        jira_result = asyncio.run(self.jira_agent.create_jira_ticket(ticket_data))
                        if jira_result.get("success"):
                            logger.info(f"Created Jira ticket for technical issue: {ticket_result.get('ticket_number')}")
                            ticket_data["jira_ticket"] = jira_result.get("jira_ticket")
                        else:
                            logger.info(f"Ticket {ticket_result.get('ticket_number')} not technical or Jira creation failed: {jira_result.get('message')}")
                    
                except Exception as e:
                    logger.error(f"Error processing email: {e}")
                    continue
            
            state["processed_tickets"] = processed_tickets
            logger.info(f"Successfully processed {len(processed_tickets)} tickets")
            return state
        
        def start_tracking(state: WorkflowState) -> WorkflowState:
            """Node: Start tracking created tickets"""
            if state.get("error") or not state.get("processed_tickets"):
                return state
            
            for ticket in state["processed_tickets"]:
                try:
                    self.tracker.start_tracking_ticket(
                        ticket["sys_id"],
                        ticket["ticket_number"],
                        ticket["email"].get("from", "")
                    )
                except Exception as e:
                    logger.error(f"Error starting ticket tracking: {e}")
                    continue
            
            logger.info(f"Started tracking for {len(state['processed_tickets'])} tickets")
            return state
        
        # Build the StateGraph
        workflow = StateGraph(WorkflowState)
        
        # Add nodes
        workflow.add_node("fetch_emails", fetch_emails)
        workflow.add_node("classify_emails", classify_emails)
        workflow.add_node("process_support_emails", process_support_emails)
        workflow.add_node("start_tracking", start_tracking)
        
        # Define the flow
        workflow.set_entry_point("fetch_emails")
        workflow.add_edge("fetch_emails", "classify_emails")
        workflow.add_edge("classify_emails", "process_support_emails")
        workflow.add_edge("process_support_emails", "start_tracking")
        workflow.add_edge("start_tracking", END)
        
        return workflow.compile()
    
    async def trigger_workflow(self):
        """Trigger the complete agentic workflow"""
        try:
            logger.info("Starting agentic workflow...")
            start_time = datetime.now()
            
            # Initialize workflow state
            initial_state = WorkflowState(
                emails=[],
                support_emails=[],
                processed_tickets=[],
                total_emails=0,
                error="",
                timestamp=start_time.isoformat(),
                last_check=self.last_check_time.isoformat()
            )
            
            # Execute the workflow
            result = await self.workflow.ainvoke(initial_state)
            
            # Update last check time
            self.last_check_time = start_time
            
            # Log workflow completion
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.info(f"Workflow completed in {duration:.2f} seconds")
            logger.info(f"Processed {result.get('total_emails', 0)} total emails")
            logger.info(f"Created {len(result.get('processed_tickets', []))} tickets")
            
            # Also trigger tracker check for existing tickets
            await self.trigger_tracker_check()
            
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise
    
    async def trigger_tracker_check(self):
        """Trigger ticket tracking check for existing tickets"""
        try:
            logger.info("Checking status of tracked tickets...")
            await self.tracker.check_all_tracked_tickets()
            logger.info("----------------------------flow completed----------------------------")
        except Exception as e:
            logger.error(f"Tracker check failed: {e}")