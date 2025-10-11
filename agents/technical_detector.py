"""
Technical Detector Agent - Uses Gemini 2.5 Flash to determine if a ticket is technical in nature
"""

import logging
from typing import Dict, Any
import google.generativeai as genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate

from utils.logger import setup_logger

logger = setup_logger(__name__)

class TechnicalDetectorAgent:
    """Agent responsible for determining if a ticket is technical in nature using Gemini 2.5 Flash"""
    
    def __init__(self, config):
        self.config = config
        
        # Configure Gemini API
        api_key = self.config.get_secret("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        
        # Initialize Gemini model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",  # Using Gemini 2.5 Flash equivalent
            google_api_key=api_key,
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=100
        )
        
        # Technical detection prompt template
        self.technical_prompt = PromptTemplate(
            input_variables=["subject", "body", "category", "subcategory"],
            template="""
You are an AI assistant that determines if a support ticket is technical in nature.

Ticket Details:
- Subject: {subject}
- Body: {body}
- Category: {category}
- Subcategory: {subcategory}

Instructions:
1. Determine if this ticket requires technical support or involves technical issues
2. Consider the following as TECHNICAL:
   - Software issues (bugs, errors, crashes)
   - Hardware problems (device malfunctions, connectivity issues)
   - Network problems (connectivity, access, configuration)
   - System errors or bugs
   - Login or authentication issues
   - API or integration problems
   - Code-related issues
   - Database problems
   - Server issues
   - Application errors or malfunctions

3. Consider the following as NON-TECHNICAL:
   - HR-related requests (benefits, time off, etc.)
   - Finance-related requests (invoices, payments)
   - Facilities issues (building maintenance, office supplies)
   - General inquiries or information requests
   - Process-related questions
   - Training requests
   - Documentation requests

Respond with exactly one word: "TECHNICAL" or "NON_TECHNICAL"

Classification:"""
        )
        
    async def is_technical_ticket(self, ticket_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine if a ticket is technical in nature
        
        Args:
            ticket_data: Dictionary containing ticket information
            
        Returns:
            Dict: Result with technical classification and confidence
        """
        try:
            # Extract relevant information from ticket data
            email_data = ticket_data.get("email", {})
            summary_data = ticket_data.get("summary", {})
            category_data = ticket_data.get("category", {})
            
            subject = email_data.get("subject", "") or summary_data.get("short_description", "")
            body = email_data.get("body_preview", "") or summary_data.get("description", "")
            category = category_data.get("category", "")
            subcategory = category_data.get("subcategory", "")
            
            # Log classification attempt
            logger.debug(f"Determining if ticket is technical: '{subject[:50]}...'")
            
            # Prepare prompt
            prompt_text = self.technical_prompt.format(
                subject=subject,
                body=body,
                category=category,
                subcategory=subcategory
            )
            
            # Get classification from Gemini
            response = self.llm.invoke([HumanMessage(content=prompt_text)])
            classification = response.content.strip().upper()
            
            # Parse result
            is_technical = classification == "TECHNICAL"
            
            # Log result
            result_text = "technical" if is_technical else "non-technical"
            logger.info(f"Ticket '{subject[:30]}...' classified as: {result_text}")
            logger.debug(f"Technical classification response: {classification}")
            
            return {
                "is_technical": is_technical,
                "confidence": "high",
                "classification": classification
            }
            
        except Exception as e:
            logger.error(f"Error determining if ticket is technical: {e}")
            # Default to treating as non-technical in case of error
            logger.warning("Defaulting to non-technical due to classification error")
            return {
                "is_technical": False,
                "confidence": "low",
                "error": str(e)
            }
            
        