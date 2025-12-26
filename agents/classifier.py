"""
Classifier Agent - Uses Gemini 2.5 Flash to classify emails as support-related or not
"""

import logging
from typing import Dict, Any
import google.generativeai as genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate

from utils.logger import setup_logger

logger = setup_logger(__name__)

class ClassifierAgent:
    """Agent responsible for classifying emails as support-related using Gemini 2.5 Flash"""
    
    def __init__(self, config):
        self.config = config
        
        # Configure Gemini API
        api_key = self.config.get_secret("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        
        # Initialize Gemini model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",  # Using Gemini 2.5 Flash equivalent
            google_api_key=api_key,
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=100
        )
        
        # Classification prompt template
        self.classification_prompt = PromptTemplate(
            input_variables=["subject", "body_preview", "sender"],
            template="""
You are an AI assistant that classifies emails as support-related or not.

Email Details:
- Subject: {subject}
- From: {sender}
- Body Preview: {body_preview}

Instructions:
1. Determine if this email requires IT/technical support, HR assistance, general help, or any other support services
2. Consider the following as SUPPORT-RELATED:
   - Technical issues (software, hardware, network problems)
   - Account access problems
   - Password resets
   - System errors or bugs
   - Service requests
   - Help with applications or tools
   - Infrastructure issues
   - General assistance requests
   - Questions about services or processes

3. Consider the following as NOT support-related:
   - Marketing emails
   - Newsletters
   - Social invitations
   - Personal conversations
   - Spam or promotional content
   - Meeting invitations (unless about support)
   - General announcements (unless requesting support)

Respond with exactly one word: "SUPPORT" or "NOT_SUPPORT"

Classification:"""
        )
    
    def classify_email(self, email_data: Dict[str, Any]) -> bool:
        """
        Classify if an email is support-related
        
        Args:
            email_data: Dictionary containing email information
            
        Returns:
            bool: True if support-related, False otherwise
        """
        try:
            subject = email_data.get("subject", "")
            body_preview = email_data.get("body_preview", "") or ""
            sender = email_data.get("from", "")
            
            # Log classification attempt
            logger.debug(f"Classifying email from {sender}: '{subject[:50]}...'")
            
            # Prepare prompt
            prompt_text = self.classification_prompt.format(
                subject=subject,
                body_preview=body_preview,
                sender=sender
            )
            
            # Get classification from Gemini
            response = self.llm.invoke([HumanMessage(content=prompt_text)])
            classification = response.content.strip().upper()
            print("Classification",classification)
            
            # Parse result
            is_support = classification == "SUPPORT"
            
            # Log result
            result_text = "support-related" if is_support else "not support-related"
            logger.info(f"Email from {sender} classified as: {result_text}")
            logger.debug(f"Classification response: {classification}")
            
            return is_support
            
        except Exception as e:
            logger.error(f"Error classifying email: {e}")
            # Default to treating as support in case of error (safer approach)
            logger.warning("Defaulting to support-related due to classification error")
            return True
    
    def classify_batch(self, emails: list) -> Dict[str, bool]:
        """
        Classify multiple emails at once
        
        Args:
            emails: List of email dictionaries
            
        Returns:
            Dict mapping email message_id to classification result
        """
        results = {}
        
        for email_data in emails:
            try:
                message_id = email_data.get("message_id", "")
                is_support = self.classify_email(email_data)
                results[message_id] = is_support
                
            except Exception as e:
                logger.error(f"Error in batch classification: {e}")
                # Default to support for safety
                results[email_data.get("message_id", "")] = True
                
        logger.info(f"Batch classified {len(results)} emails")
        return results
    
    def _is_obvious_spam(self, email_data: Dict[str, Any]) -> bool:
        """
        Quick check for obvious spam/promotional emails before using Gemini
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            bool: True if obviously spam/promotional
        """
        subject = email_data.get("subject", "").lower()
        sender = email_data.get("from", "").lower()
        
        # Common spam indicators
        spam_subjects = [
            "unsubscribe", "promotion", "sale", "offer", "discount",
            "free", "winner", "congratulations", "click here",
            "limited time", "act now", "bonus", "cash", "prize"
        ]
        
        spam_senders = [
            "noreply", "no-reply", "donotreply", "marketing",
            "newsletter", "promo", "offers"
        ]
        
        # Check subject for spam indicators
        if any(spam_word in subject for spam_word in spam_subjects):
            return True
            
        # Check sender for spam indicators
        if any(spam_word in sender for spam_word in spam_senders):
            return True
            
        return False
    
    def enhanced_classify_email(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhanced classification with additional metadata
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            Dict with classification result and confidence/reasoning
        """
        try:
            # Quick spam check first
            if self._is_obvious_spam(email_data):
                return {
                    "is_support": False,
                    "confidence": "high",
                    "reason": "Identified as promotional/spam content"
                }
            
            # Use regular classification
            is_support = self.classify_email(email_data)
            
            return {
                "is_support": is_support,
                "confidence": "medium",
                "reason": "AI classification using Gemini"
            }
            
        except Exception as e:
            logger.error(f"Error in enhanced classification: {e}")
            return {
                "is_support": True,  # Default to support for safety
                "confidence": "low",
                "reason": f"Classification error, defaulting to support: {str(e)}"
            }

