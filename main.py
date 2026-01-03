"""
FastAPI Application for Automated ServiceNow Ticket Creation from Gmail
Main application entry point with background scheduler for agentic workflow
"""

import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException , Request
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agents.scheduler import SchedulerAgent
from utils.logger import setup_logger
from tools.config_loader import ConfigLoader

# Setup logging
logger = setup_logger(__name__)

# Global scheduler instance
scheduler = None
scheduler_agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown events"""
    global scheduler, scheduler_agent
    
    try:
        # Load configuration
        config = ConfigLoader()
        
        # Initialize scheduler agent
        scheduler_agent = SchedulerAgent(config)
        
        # Create and start the background scheduler
        scheduler = AsyncIOScheduler()
        
        # Add job to check emails every 10 minutes
        scheduler.add_job(
            func=scheduler_agent.trigger_workflow,
            trigger=IntervalTrigger(minutes=1),
            id='email_check_job',
            name='Check emails and process tickets',
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("Background scheduler started - checking emails every 10 minutes")
        
        # Initial run
        asyncio.create_task(scheduler_agent.trigger_workflow())
        logger.info("Initial workflow triggered")
        
        yield
        
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise
    finally:
        # Cleanup on shutdown
        if scheduler:
            scheduler.shutdown()
            logger.info("Background scheduler stopped")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="ServiceNow Ticket Automation",
    description="Automated ticket creation from Gmail emails using agentic AI workflow",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "message": "ServiceNow Ticket Automation Service is active",
        "scheduler_status": "running" if scheduler and scheduler.running else "stopped"
    }

def extract_servicenow_ticket_id(jira_title: str) -> str:
    """
    Extract ServiceNow ticket ID from Jira issue title
    Format expected: [INC0001234] Issue title
    
    Args:
        jira_title: The title of the Jira issue
        
    Returns:
        ServiceNow ticket ID or empty string if not found
    """
    import re
    # Look for text in square brackets at the beginning of the title
    match = re.match(r'^\[(.*?)\]', jira_title)
    if match:
        return match.group(1).strip()
    return ""

@app.post("/rest/webhooks/webhook1")
async def jira_webhook(request: Request):
    """
    Webhook handler for Jira status updates.
    Syncs Jira issue status changes to ServiceNow incident states.
    """
    try:
        # --- Parse webhook payload ---
        data = await request.json()
        issue_data = data.get("issue", {})
        issue_fields = issue_data.get("fields", {})
        issue_title = issue_fields.get("summary", "")
        issue_status = issue_fields.get("status", {}).get("name", "")

        if not issue_title or not issue_status:
            logger.warning("Missing title or status in Jira webhook payload")
            return {"message": "Webhook received but missing required data"}

        # --- Extract ServiceNow ticket ID from Jira title ---
        servicenow_ticket_id = extract_servicenow_ticket_id(issue_title)

        if not servicenow_ticket_id:
            logger.warning(f"Could not extract ServiceNow ticket ID from Jira title: {issue_title}")
            return {"message": "Webhook received but no ServiceNow ticket ID found in title"}

        # --- Map Jira statuses to ServiceNow states ---
        status_mapping = {
            "To Do": "1",        # New
            "In Progress": "2",  # In Progress
            "In Review": "2",    # In Progress
            "On Hold": "3",      # On Hold
            "Done": "6",         # Resolved
            "Resolved": "6",     # Resolved
            "Closed": "7"        # Closed
        }

        servicenow_state = status_mapping.get(issue_status)
        if not servicenow_state:
            logger.warning(f"No mapping found for Jira status: {issue_status}")
            return {"message": f"Webhook received but no mapping for status: {issue_status}"}

        # --- Initialize ServiceNow API ---
        from tools.servicenow_api import ServiceNowAPI
        from tools.config_loader import ConfigLoader

        config = ConfigLoader()
        servicenow_api = ServiceNowAPI(config)

        # --- Lookup the incident in ServiceNow by ticket number ---
        logger.info(f"Looking up ServiceNow incident with number: {servicenow_ticket_id}")
        incidents = servicenow_api._make_request(
            "GET",
            "incident",
            params={
                "sysparm_query": f"number={servicenow_ticket_id}", 
                "sysparm_limit": 1,
                "sysparm_fields": "sys_id,number,short_description,state,incident_state,caller_id,work_notes,resolution_notes"
            }
        )

        result_list = incidents.get("data", {}).get("result", [])
        if not incidents.get("success") or not result_list:
            logger.error(f"Could not find ServiceNow incident with number: {servicenow_ticket_id}")
            return {"message": f"Incident not found: {servicenow_ticket_id}"}

        sys_id = result_list[0].get("sys_id")
        logger.info(f"Found ServiceNow incident with sys_id: {sys_id}")

        # --- Prepare update payload ---
        update_data = {
            "state": servicenow_state,
            "work_notes": f"Status updated from Jira: {issue_status}"
        }

        # --- If Jira marks issue as Done or Closed, include close details ---
        if servicenow_state in ["6", "7"]:
            update_data.update({
                "close_code": "Resolved by request",
                "close_notes": "Automatically resolved via Jira webhook"
            })

        # --- Perform update using direct PATCH request ---
        logger.info(f"Updating ServiceNow incident {servicenow_ticket_id} with sys_id {sys_id}")
        result = servicenow_api._make_request(
            "PATCH",
            f"incident/{sys_id}",
            data=update_data
        )

        if result.get("success"):
            logger.info(
                f"✅ Updated ServiceNow incident {servicenow_ticket_id} "
                f"to state {servicenow_state} ({issue_status})"
            )
            
            # --- Send email notification to ticket recipients ---
            try:
                # Get ticket details for email notification
                ticket_details = result_list[0]
                logger.info(f"ServiceNow ticket details: {ticket_details}")
                caller_sys_id = ticket_details.get("caller_id", "")
                logger.info(f"DEBUG: caller_id type: {type(caller_sys_id)}, value: {caller_sys_id}")
                
                # Handle case where caller_id is a dict (link/value)
                if isinstance(caller_sys_id, dict):
                    caller_sys_id = caller_sys_id.get("value", "")
                elif isinstance(caller_sys_id, str) and caller_sys_id.strip().startswith('{'):
                    try:
                        import ast
                        caller_dict = ast.literal_eval(caller_sys_id)
                        if isinstance(caller_dict, dict):
                            caller_sys_id = caller_dict.get("value", "")
                            logger.info(f"DEBUG: Extracted sys_id from string dict: {caller_sys_id}")
                    except Exception as e:
                        logger.warning(f"Failed to parse caller_id string: {e}")
                short_description = ticket_details.get("short_description", "Support Request")
                
                # Lookup caller email using caller sys_id
                caller_email = ""
                if caller_sys_id:
                    logger.info(f"Looking up caller email for sys_id: {caller_sys_id}")
                    caller_lookup = servicenow_api.lookup_user_by_sys_id(caller_sys_id)
                    if caller_lookup.get("found"):
                        caller_email = caller_lookup.get("email", "")
                        logger.info(f"Found caller email: {caller_email}")
                    else:
                        logger.warning(f"Caller lookup failed: {caller_lookup.get('error', 'Unknown error')}")
                else:
                    logger.warning(f"No caller sys_id found for ticket {servicenow_ticket_id}")
                
                if caller_email:
                    # Initialize notification agent
                    from agents.notification import NotificationAgent
                    notification_agent = NotificationAgent(config)
                    
                    # Map ServiceNow state to status name for email
                    status_names = {
                        "1": "New",
                        "2": "In Progress", 
                        "3": "On Hold",
                        "6": "Resolved",
                        "7": "Closed"
                    }
                    status_name = status_names.get(servicenow_state, "Updated")
                    
                    # Prepare update notes
                    update_notes = f"Ticket status changed to {status_name} via Jira update"
                    if servicenow_state in ["6", "7"]:
                        update_notes += "\n\nResolution: Automatically resolved via Jira webhook"
                    
                    # Send update email
                    email_result = notification_agent.send_update_email(
                        recipient_email=caller_email,
                        ticket_number=servicenow_ticket_id,
                        short_description=short_description,
                        update_notes=update_notes,
                        status=status_name
                    )
                    
                    if email_result.get("success"):
                        logger.info(f"✅ Email notification sent to {caller_email} for ticket {servicenow_ticket_id}")
                    else:
                        logger.warning(f"⚠️ Failed to send email notification: {email_result.get('error')}")
                else:
                    logger.warning(f"No caller email found for ticket {servicenow_ticket_id}, skipping email notification")
                    
            except Exception as email_error:
                logger.error(f"Error sending email notification: {email_error}")
                # Don't fail the webhook if email fails
            
            return {
                "message": "ServiceNow ticket updated successfully",
                "ticket_id": servicenow_ticket_id,
                "new_state": servicenow_state
            }
        else:
            error_detail = result.get("error") or result
            logger.error(f"❌ Failed to update ServiceNow incident: {error_detail}")
            return {"message": f"Error updating ServiceNow ticket: {error_detail}"}

    except Exception as e:
        logger.exception(f"Unhandled exception in Jira webhook: {str(e)}")
        return {"message": f"Error processing webhook: {str(e)}"}

@app.get("/health")
async def health_check():
    """Detailed health check endpoint"""
    try:
        config_status = ConfigLoader().validate_config()
        return {
            "status": "healthy",
            "scheduler_running": scheduler.running if scheduler else False,
            "config_valid": config_status,
            "next_run": str(scheduler.get_job('email_check_job').next_run_time) if scheduler else None
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@app.post("/trigger-manual")
async def trigger_manual():
    """Manual trigger endpoint for testing purposes"""
    try:
        if scheduler_agent:
            await scheduler_agent.trigger_workflow()
            return {"status": "success", "message": "Workflow triggered manually"}
        else:
            raise HTTPException(status_code=500, detail="Scheduler agent not initialized")
    except Exception as e:
        logger.error(f"Manual trigger failed: {e}")
        raise HTTPException(status_code=500, detail=f"Manual trigger failed: {str(e)}")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload in production
        log_level="info"
    )