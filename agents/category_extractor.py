"""
Category Extractor Agent - Uses Gemini 2.5 Flash to extract incident categories (IT, HR, Finance, etc.)
"""

import logging
from typing import Dict, Any
import google.generativeai as genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
import re
import json
from utils.logger import setup_logger

logger = setup_logger(__name__)

class CategoryExtractorAgent:
    """Agent responsible for extracting incident categories using Gemini 2.5 Flash"""
    
    def __init__(self, config):
        self.config = config
        
        # Configure Gemini API
        api_key = self.config.get_secret("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        
        # Initialize Gemini model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",  # Using Gemini 2.5 Flash equivalent
            google_api_key=api_key,
            temperature=0.1,  # Low temperature for consistent categorization
            max_tokens=200
        )
        
        # Get available categories from config
        self.available_categories = self.config.get_setting("incident_categories", {})
        
        # Category extraction prompt template
        self.category_prompt = PromptTemplate(
            input_variables=["subject", "body_preview", "sender", "categories"],
            template="""
You are an AI assistant that categorizes support tickets based on email content.

Email Information:
- Subject: {subject}
- From: {sender}
- Body Preview: {body_preview}

Available Categories:
{categories}

Instructions:
1. Analyze the email content to determine the most appropriate category
2. Consider the subject, sender, and any available body content
3. Match to one of the available categories listed above
4. Also suggest priority and urgency levels (1-4 scale: 1=Critical, 2=High, 3=Medium, 4=Low)

Category Guidelines:
- IT/Technical: Software issues, hardware problems, network issues, system errors, login problems
- HR/Human Resources: Employee issues, policy questions, benefits, onboarding, offboarding
- Finance/Accounting: Invoice issues, expense reports, budget questions, payment problems
- Facilities: Office space, maintenance, security access, parking, utilities
- General: Anything that doesn't clearly fit other categories

Respond in JSON format:
{{
    "category": "Primary category name",
    "subcategory": "More specific subcategory if applicable",
    "confidence": "high|medium|low",
    "priority": "1-4",
    "urgency": "1-4",
    "reasoning": "Brief explanation of why this category was chosen"
}}

Response:"""
        )
    
    def extract_category(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract category information from email
        
        Args:
            email_data: Dictionary containing email information
            
        Returns:
            Dict containing category, priority, urgency, and reasoning
        """
        try:
            subject = email_data.get("subject", "")
            body_preview = email_data.get("body_preview", "") or ""
            sender = email_data.get("from", "")
            
            logger.debug(f"Extracting category for email from {sender}")
            
            # Format available categories for prompt
            categories_text = self._format_categories_for_prompt()
            
            # Prepare prompt
            prompt_text = self.category_prompt.format(
                subject=subject,
                body_preview=body_preview,
                sender=sender,
                categories=categories_text
            )
            
            # Get categorization from Gemini
            response = self.llm.invoke([HumanMessage(content=prompt_text)])
            result_text = response.content.strip()
            
            # Parse JSON response
            import json
            try:
               
                # Remove Markdown-style code fences if present
                cleaned_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", result_text, flags=re.DOTALL).strip()
                print("data",cleaned_text)
                category_data = json.loads(cleaned_text)
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON response, using fallback categorization")
                category_data = self._create_fallback_category(email_data)
            
            # Validate and enhance category data
            category_result = self._validate_category_data(category_data)
            
            logger.info(f"Email categorized as: {category_result['category']} (confidence: {category_result['confidence']})")
            return category_result
            
        except Exception as e:
            logger.error(f"Error extracting category: {e}")
            return self._create_fallback_category(email_data)
    
    def _format_categories_for_prompt(self) -> str:
        """Format available categories for the prompt"""
        if not self.available_categories:
            return """
- IT/Technical: Software, hardware, network, system issues
- HR/Human Resources: Employee matters, policies, benefits
- Finance/Accounting: Invoices, expenses, payments
- Facilities: Office space, maintenance, access
- General: Other support requests
"""
        
        formatted = []
        for category, details in self.available_categories.items():
            if isinstance(details, dict):
                description = details.get("description", "")
                subcategories = details.get("subcategories", [])
                
                line = f"- {category}: {description}"
                if subcategories:
                    line += f" (subcategories: {', '.join(subcategories)})"
                formatted.append(line)
            else:
                formatted.append(f"- {category}")
        
        return "\n".join(formatted)
    
    def _validate_category_data(self, category_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean category data"""
        
        # Get category or use fallback
        category = category_data.get("category", "General")
        
        # Validate category exists in available categories
        if self.available_categories and category not in self.available_categories:
            # Try to find a close match
            category = self._find_closest_category(category)
        
        # Validate priority and urgency (1-4)
        try:
            priority = int(category_data.get("priority", 3))
            priority = str(max(1, min(4, priority)))
        except (ValueError, TypeError):
            priority = "3"
        
        try:
            urgency = int(category_data.get("urgency", 3))
            urgency = str(max(1, min(4, urgency)))
        except (ValueError, TypeError):
            urgency = "3"
        
        # Validate confidence
        confidence = category_data.get("confidence", "medium").lower()
        if confidence not in ["high", "medium", "low"]:
            confidence = "medium"
        
        return {
            "category": category,
            "subcategory": category_data.get("subcategory", ""),
            "confidence": confidence,
            "priority": priority,
            "urgency": urgency,
            "reasoning": category_data.get("reasoning", f"Categorized as {category}")
        }
    
    def _find_closest_category(self, suggested_category: str) -> str:
        """Find the closest matching category from available categories"""
        suggested_lower = suggested_category.lower()
        
        # Check for exact matches first
        for available_category in self.available_categories.keys():
            if suggested_lower == available_category.lower():
                return available_category
        
        # Check for partial matches
        for available_category in self.available_categories.keys():
            if suggested_lower in available_category.lower() or available_category.lower() in suggested_lower:
                return available_category
        
        # Common category mappings
        category_mappings = {
            "technical": "IT",
            "technology": "IT",
            "computer": "IT",
            "software": "IT",
            "hardware": "IT",
            "network": "IT",
            "human resources": "HR",
            "employee": "HR",
            "payroll": "HR",
            "benefits": "HR",
            "accounting": "Finance",
            "invoice": "Finance",
            "payment": "Finance",
            "expense": "Finance",
            "office": "Facilities",
            "building": "Facilities",
            "maintenance": "Facilities"
        }
        
        for keyword, mapped_category in category_mappings.items():
            if keyword in suggested_lower:
                if mapped_category in self.available_categories:
                    return mapped_category
        
        # Return default category
        return "General"
    
    def _create_fallback_category(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create fallback category when extraction fails"""
        subject = email_data.get("subject", "").lower()
        
        # Simple keyword-based categorization
        if any(word in subject for word in ["password", "login", "software", "computer", "network", "system"]):
            category = "IT"
        elif any(word in subject for word in ["hr", "employee", "payroll", "benefits"]):
            category = "HR"
        elif any(word in subject for word in ["invoice", "payment", "expense", "finance"]):
            category = "Finance"
        elif any(word in subject for word in ["office", "facility", "maintenance", "access"]):
            category = "Facilities"
        else:
            category = "General"
        
        return {
            "category": category,
            "subcategory": "",
            "confidence": "low",
            "priority": "3",
            "urgency": "3",
            "reasoning": f"Fallback categorization based on subject keywords"
        }
    
    def extract_category_with_rules(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract category using both AI and rule-based approaches
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            Enhanced category information
        """
        try:
            # Get AI-based categorization
            ai_result = self.extract_category(email_data)
            
            # Apply business rules for refinement
            refined_result = self._apply_business_rules(email_data, ai_result)
            
            return refined_result
            
        except Exception as e:
            logger.error(f"Error in rule-based category extraction: {e}")
            return self._create_fallback_category(email_data)
    
    def _apply_business_rules(self, email_data: Dict[str, Any], ai_result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply business rules to refine AI categorization"""
        
        subject = email_data.get("subject", "").lower()
        sender = email_data.get("from", "").lower()
        
        # Rule 1: Urgent keywords increase priority
        urgent_keywords = ["urgent", "critical", "emergency", "down", "outage", "broken"]
        if any(keyword in subject for keyword in urgent_keywords):
            ai_result["priority"] = "1"
            ai_result["urgency"] = "1"
        
        # Rule 2: Specific sender domains may indicate category
        if "hr@" in sender or "people@" in sender:
            ai_result["category"] = "HR"
            ai_result["confidence"] = "high"
        
        if "finance@" in sender or "accounting@" in sender:
            ai_result["category"] = "Finance"
            ai_result["confidence"] = "high"
        
        if "it@" in sender or "tech@" in sender or "support@" in sender:
            ai_result["category"] = "IT"
            ai_result["confidence"] = "high"
        
        # Rule 3: Password/access issues are always IT
        if any(word in subject for word in ["password", "login", "access denied", "locked out"]):
            ai_result["category"] = "IT"
            ai_result["subcategory"] = "Access Management"
            ai_result["priority"] = "2"  # High priority for access issues
        
        return ai_result