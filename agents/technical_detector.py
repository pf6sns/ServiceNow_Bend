"""
Technical Detector Agent - Uses Groq API to determine if a ticket is technical in nature
"""

import logging
from typing import Dict, Any
from groq import Groq
from langchain_core.prompts import PromptTemplate

from utils.logger import setup_logger

logger = setup_logger(__name__)

class TechnicalDetectorAgent:
    """Agent responsible for determining if a ticket is technical in nature using Groq API"""
    
    def __init__(self, config):
        self.config = config
        
        # Initialize Groq client
        api_key = self.config.get_secret("GROQ_API_KEY")
        self.client = Groq(api_key=api_key)
        # Use Llama-3.1-8B-Instant model (replacement for decommissioned Mixtral)
        self.model = "Llama-3.1-8B-Instant"
        
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
            logger.info(f"🔍 Technical Detection - Analyzing ticket: '{subject[:50]}...'")
            logger.debug(f"Category: {category}, Body preview: {body[:100]}...")
            
            # Prepare prompt
            prompt_text = self.technical_prompt.format(
                subject=subject,
                body=body,
                category=category,
                subcategory=subcategory
            )
            
            # Get classification from Groq
            message = self.client.chat.completions.create(
                model=self.model,
                max_tokens=100,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt_text}]
            )
            
            classification = message.choices[0].message.content.strip().upper()
            
            # Parse result
            is_technical = classification == "TECHNICAL"
            
            # Log result
            result_text = "✅ TECHNICAL" if is_technical else "❌ NON-TECHNICAL"
            logger.info(f"Technical Detection Result: {result_text}")
            logger.info(f"Ticket: '{subject[:50]}...'")
            logger.debug(f"Full classification response: {classification}")
            
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
            
        