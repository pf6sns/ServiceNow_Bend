from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Optional, List, Dict, Any
from tools.servicenow_api import ServiceNowAPI
from tools.config_loader import ConfigLoader
from utils.db import get_all_tickets, get_ticket, get_ticket_history, get_ticket_by_number

router = APIRouter(prefix="/servicenow", tags=["ServiceNow Tickets"])

def get_servicenow_api():
    config = ConfigLoader()
    return ServiceNowAPI(config)

@router.get("/tickets")
async def get_tickets(
    limit: int = 50, 
    offset: int = 0
):
    """
    Fetch tracked tickets from local database (Workflow view)
    """
    try:
        tickets = get_all_tickets()
        
        # Map fields to match ServiceNow original API response for compatibility
        mapped_tickets = []
        for t in tickets:
            # Handle potential missing fields gracefully
            mapped_tickets.append({
                "sys_id": t["sys_id"],
                "number": t["ticket_number"],
                "short_description": t["short_description"] or "",
                "description": t["description"] or "",
                "state": t["status"] or "1",
                "priority": t["priority"] or "3",
                "category": t["category"] or "",
                "assigned_to": t["assigned_to"] or "",
                "assignment_group": t["assignment_group"] or "",
                "caller_id": t["caller_email"] or "", # Use email as caller identifier
                "sys_created_on": t["created_at"] or "",
                "sys_updated_on": t["updated_at"] or "",
                "jira_ticket_id": t.get("jira_ticket_id")
            })
            
        return {"tickets": mapped_tickets}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tickets/{ticket_number}")
async def get_ticket_details(
    ticket_number: str,
    servicenow_api: ServiceNowAPI = Depends(get_servicenow_api)
):
    """
    Fetch a single ticket with history
    """
    try:
        # 1. Try to find in local DB first to get history
        ticket_entry = get_ticket_by_number(ticket_number)
        
        formatted_ticket = {}
        history = []
        found_in_db = False
        
        if ticket_entry:
            sys_id = ticket_entry['sys_id']
            # Get history
            history_rows = get_ticket_history(sys_id)
            history = [dict(h) for h in history_rows] # ensure dict
            
            # Use mapped fields for consistent frontend consumption
            formatted_ticket = {
                "sys_id": ticket_entry["sys_id"],
                "number": ticket_entry["ticket_number"],
                "short_description": ticket_entry["short_description"] or "",
                "description": ticket_entry["description"] or "",
                "state": ticket_entry["status"] or "1",
                "priority": ticket_entry["priority"] or "3",
                "category": ticket_entry["category"] or "",
                "assigned_to": ticket_entry["assigned_to"] or "",
                "assignment_group": ticket_entry["assignment_group"] or "",
                "caller_id": ticket_entry["caller_email"] or "", 
                "sys_created_on": ticket_entry["created_at"] or "",
                "sys_updated_on": ticket_entry["updated_at"] or "",
                "jira_ticket_id": ticket_entry.get("jira_ticket_id")
            }
            found_in_db = True
            
        if not found_in_db:
            # Fallback to ServiceNow API if not found in local DB (e.g. old ticket)
            # Find sys_id first
            query_params = {
                "sysparm_query": f"number={ticket_number}",
                "sysparm_limit": "1"
            }
            search_result = servicenow_api.search_incidents(query_params, 1)
             
            if search_result.get("success") and search_result.get("incidents"):
                sn_ticket = search_result.get("incidents")[0]
                sys_id = sn_ticket.get("sys_id")
                
                # Get full details from ServiceNow
                result = servicenow_api.get_incident(sys_id)
                if result.get("found"):
                    formatted_ticket = result
                else: 
                     raise HTTPException(status_code=404, detail="Ticket details not found")
            else:
                 raise HTTPException(status_code=404, detail="Ticket not found in ServiceNow")

        return {
            "ticket": formatted_ticket,
            "history": history
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
