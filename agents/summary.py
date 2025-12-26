"""
Summary Agent - Uses Gemini 2.5 Flash to generate concise problem summaries and ticket descriptions
"""

import logging
from typing import Dict, Any
import google.generativeai as genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
import json
import re

from utils.logger import setup_logger

logger = setup_logger(__name__)

class SummaryAgent:
    """Agent responsible for generating summaries and ticket descriptions using Gemini 2.5 Flash"""
    
    def __init__(self, config):
        self.config = config
        
        # Configure Gemini API
        api_key = self.config.get_secret("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        
        # Initialize Gemini model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",  # Using Gemini 2.5 Flash equivalent
            google_api_key=api_key,
            temperature=0.3,  # Slightly higher for creative summaries
            max_tokens=300
        )
        
        # Summary prompt template
        self.summary_prompt = PromptTemplate(
            input_variables=["subject", "body_preview", "sender"],
            template="""
You are an AI assistant that creates concise, professional summaries for IT support tickets.

Email Information:
- Subject: {subject}
- From: {sender}
- Body Preview: {body_preview}

Instructions:
1. Create a SHORT, clear title/short_description (max 80 characters)
2. Write a CONCISE description of the issue (max 200 words)
3. Focus on the actual problem, not email metadata
4. Use professional, technical language appropriate for support tickets
5. If the subject is clear enough, use it as basis for the title
6. If information is limited, make reasonable assumptions about the support need

Format your response as JSON:
{{
    "short_description": "Brief title of the issue",
    "description": "Detailed description of the problem and any relevant context",
    "priority_suggested": "1-4 (1=Critical, 2=High, 3=Medium, 4=Low)",
    "urgency_suggested": "1-4 (1=Critical, 2=High, 3=Medium, 4=Low)"
}}

Response:"""
        )
    
    def generate_summary(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate summary and ticket description for an email
        
        Args:
            email_data: Dictionary containing email information
            
        Returns:
            Dict containing short_description, description, and priority suggestions
        """
        try:
            subject = email_data.get("subject", "Support Request")
            body_preview = email_data.get("body_preview", "") or ""
            sender = email_data.get("from", "unknown@email.com")
            
            logger.debug(f"Generating summary for email from {sender}")
            
            # Prepare prompt
            prompt_text = self.summary_prompt.format(
                subject=subject,
                body_preview=body_preview,
                sender=sender
            )
            
            # Get summary from Gemini
            response = self.llm.invoke([HumanMessage(content=prompt_text)])
            result_text = response.content.strip()
            
            # Parse JSON response
            import json
            try:
                result_text = response.content.strip()
                # Remove Markdown-style code fences if present
                cleaned_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", result_text, flags=re.DOTALL).strip()
                
                # Try to extract JSON if embedded in other text
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_text, re.DOTALL)
                if json_match:
                    cleaned_text = json_match.group(0)
                
                logger.debug(f"Parsing JSON response: {cleaned_text[:200]}...")
                summary_data = json.loads(cleaned_text)
                
            except (json.JSONDecodeError, AttributeError) as e:
                # Fallback if JSON parsing fails
                logger.warning(f"Failed to parse JSON response: {e}. Using fallback")
                logger.debug(f"Raw response was: {result_text[:500]}")
                summary_data = self._create_fallback_summary(email_data)
            
            # Validate and clean data
            summary_result = {
                "short_description": summary_data.get("short_description", subject)[:80],
                "description": summary_data.get("description", f"Support request from {sender}")[:500],
                "priority_suggested": str(summary_data.get("priority_suggested", "3")),
                "urgency_suggested": str(summary_data.get("urgency_suggested", "3"))
            }
            
            logger.info(f"Generated summary: '{summary_result['short_description']}'")
            return summary_result
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return self._create_fallback_summary(email_data)
    
    def _create_fallback_summary(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a fallback summary when AI generation fails
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            Dict with basic summary information
        """
        subject = email_data.get("subject", "Support Request")
        sender = email_data.get("from", "unknown@email.com")
        
        # Clean and truncate subject
        clean_subject = subject.strip()
        if not clean_subject:
            clean_subject = "General Support Request"
        
        return {
            "short_description": clean_subject[:80],
            "description": f"Support request from {sender}.\nOriginal subject: {subject}",
            "priority_suggested": "3",
            "urgency_suggested": "3"
        }
    
    def generate_batch_summaries(self, emails: list) -> Dict[str, Dict[str, Any]]:
        """
        Generate summaries for multiple emails
        
        Args:
            emails: List of email dictionaries
            
        Returns:
            Dict mapping email message_id to summary data
        """
        summaries = {}
        
        for email_data in emails:
            try:
                message_id = email_data.get("message_id", "")
                summary = self.generate_summary(email_data)
                summaries[message_id] = summary
                
            except Exception as e:
                logger.error(f"Error in batch summary generation: {e}")
                summaries[email_data.get("message_id", "")] = self._create_fallback_summary(email_data)
        
        logger.info(f"Generated summaries for {len(summaries)} emails")
        return summaries
    
    def enhance_summary_with_context(self, email_data: Dict[str, Any], category_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance summary with category-specific context
        
        Args:
            email_data: Email data dictionary
            category_info: Category information from category extractor
            
        Returns:
            Enhanced summary dictionary
        """
        try:
            # Get base summary
            summary = self.generate_summary(email_data)
            
            # Enhance based on category
            category = category_info.get("category", "General")
            
            # Category-specific enhancements
            if category.lower() in ["it", "technical", "software", "hardware"]:
                summary["priority_suggested"] = "2"  # Higher priority for IT issues
                summary["description"] += f"\n\nCategory: {category} - Technical support required"
            
            elif category.lower() in ["hr", "human resources"]:
                summary["description"] += f"\n\nCategory: {category} - HR assistance required"
            
            elif category.lower() in ["finance", "accounting"]:
                summary["description"] += f"\n\nCategory: {category} - Financial support required"
            
            # Add category to description
            if not category.lower() == "general":
                summary["category"] = category
            
            return summary
            
        except Exception as e:
            logger.error(f"Error enhancing summary with context: {e}")
            return self.generate_summary(email_data)
    
    def validate_summary(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and clean summary data
        
        Args:
            summary: Summary dictionary to validate
            
        Returns:
            Validated and cleaned summary dictionary
        """
        validated = {}
        
        # Validate short_description
        short_desc = summary.get("short_description", "Support Request")
        validated["short_description"] = str(short_desc)[:80].strip()
        
        # Validate description
        description = summary.get("description", "General support request")
        validated["description"] = str(description)[:500].strip()
        
        # Validate priority (1-4)
        try:
            priority = int(summary.get("priority_suggested", 3))
            validated["priority_suggested"] = str(max(1, min(4, priority)))
        except (ValueError, TypeError):
            validated["priority_suggested"] = "3"
        
        # Validate urgency (1-4)
        try:
            urgency = int(summary.get("urgency_suggested", 3))
            validated["urgency_suggested"] = str(max(1, min(4, urgency)))
        except (ValueError, TypeError):
            validated["urgency_suggested"] = "3"
        
        return validated