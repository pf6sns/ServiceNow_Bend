"""
Configuration Loader - Loads configuration from .env and config.yaml files
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

from utils.logger import setup_logger

logger = setup_logger(__name__)

class ConfigLoader:
    """Configuration loader for environment variables and YAML settings"""
    
    def __init__(self, env_file: str = ".env", config_file: str = "config/config.yaml"):
        self.env_file = env_file
        self.config_file = config_file
        self.config_data = {}
        
        # Load configuration
        self._load_environment()
        self._load_yaml_config()
        
        logger.info("Configuration loaded successfully")
    
    def _load_environment(self):
        """Load environment variables from .env file"""
        try:
            if os.path.exists(self.env_file):
                load_dotenv(self.env_file)
                logger.info(f"Loaded environment variables from {self.env_file}")
            else:
                logger.warning(f"Environment file {self.env_file} not found, using system environment")
                
        except Exception as e:
            logger.error(f"Error loading environment file: {e}")
    
    def _load_yaml_config(self):
        """Load configuration from YAML file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as file:
                    self.config_data = yaml.safe_load(file) or {}
                logger.info(f"Loaded configuration from {self.config_file}")
            else:
                logger.warning(f"Config file {self.config_file} not found, using defaults")
                self.config_data = self._get_default_config()
                
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config file: {e}")
            self.config_data = self._get_default_config()
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            self.config_data = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration when config file is not available"""
        return {
            "servicenow_fallbacks": {
                "default_caller": {
                    "sys_id": "",
                    "name": "Unknown Caller",
                    "email": "unknown@company.com"
                },
                "default_assignment_group": {
                    "sys_id": "",
                    "name": "General Support"
                }
            },
            "incident_categories": {
                "IT": {
                    "description": "Information Technology issues",
                    "subcategories": ["Software", "Hardware", "Network", "Access"]
                },
                "HR": {
                    "description": "Human Resources matters",
                    "subcategories": ["Benefits", "Payroll", "Policies", "Onboarding"]
                },
                "Finance": {
                    "description": "Financial and accounting issues",
                    "subcategories": ["Invoices", "Expenses", "Budget", "Payments"]
                },
                "Facilities": {
                    "description": "Office and facilities management",
                    "subcategories": ["Maintenance", "Access", "Equipment", "Space"]
                },
                "General": {
                    "description": "General support requests",
                    "subcategories": ["Information", "Other"]
                }
            },
            "category_to_group": {
                "IT": "IT Support",
                "HR": "Human Resources",
                "Finance": "Finance Team",
                "Facilities": "Facilities Management",
                "General": "General Support"
            },
            "category_to_user": {
                "IT": "",
                "HR": "",
                "Finance": "",
                "Facilities": "",
                "General": ""
            },
            "servicenow_category_mapping": {
                "IT": "Software",
                "HR": "Human Resources",
                "Finance": "Finance",
                "Facilities": "Facilities",
                "General": "General"
            },
            "email_templates": {
                "ticket_created": {
                    "subject": "Support Ticket Created - {ticket_number}",
                    "body": "Your support ticket {ticket_number} has been created and assigned to {assigned_group}."
                },
                "ticket_closed": {
                    "subject": "Support Ticket Resolved - {ticket_number}",
                    "body": "Your support ticket {ticket_number} has been resolved."
                }
            },
            "from_name": "IT Support System",
            "create_unknown_users": False,
            "send_status_updates": False
        }
    
    def get_secret(self, key: str, default: str = None) -> Optional[str]:
        """
        Get secret value from environment variables
        
        Args:
            key: Environment variable key
            default: Default value if key not found
            
        Returns:
            Secret value or default
        """
        value = os.getenv(key, default)
        if value is None:
            logger.warning(f"Secret '{key}' not found in environment")
        return value
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get configuration setting from YAML config
        
        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        try:
            # Support dot notation for nested keys
            keys = key.split('.')
            value = self.config_data
            
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            
            return value
            
        except Exception as e:
            logger.warning(f"Error getting setting '{key}': {e}")
            return default
    
    def get_required_secret(self, key: str) -> str:
        """
        Get required secret value (raises exception if not found)
        
        Args:
            key: Environment variable key
            
        Returns:
            Secret value
            
        Raises:
            ValueError: If secret is not found
        """
        value = self.get_secret(key)
        if value is None:
            raise ValueError(f"Required secret '{key}' not found in environment")
        return value
    
    def get_all_secrets(self) -> Dict[str, str]:
        """
        Get all environment variables (for debugging - be careful with logging)
        
        Returns:
            Dict of environment variables
        """
        # Only return non-sensitive environment variables
        safe_vars = {}
        for key, value in os.environ.items():
            # Skip sensitive keys
            if any(sensitive in key.upper() for sensitive in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
                safe_vars[key] = "***HIDDEN***"
            else:
                safe_vars[key] = value
        return safe_vars
    
    def get_all_settings(self) -> Dict[str, Any]:
        """
        Get all configuration settings
        
        Returns:
            Dict of all configuration settings
        """
        return self.config_data.copy()
    
    def validate_config(self) -> bool:
        """
        Validate that all required configuration is present
        
        Returns:
            bool: True if configuration is valid
        """
        try:
            required_secrets = [
                "GMAIL_EMAIL",
                "GMAIL_APP_PASSWORD", 
                "SERVICENOW_INSTANCE_URL",
                "SERVICENOW_USERNAME",
                "SERVICENOW_PASSWORD",
                "GROQ_API_KEY",
                "SMTP_USERNAME",
                "SMTP_PASSWORD"
            ]
            
            missing_secrets = []
            for secret in required_secrets:
                if not self.get_secret(secret):
                    missing_secrets.append(secret)
            
            if missing_secrets:
                logger.error(f"Missing required secrets: {missing_secrets}")
                return False
            
            # Validate YAML config structure
            required_sections = ["servicenow_fallbacks", "incident_categories"]
            for section in required_sections:
                if not self.get_setting(section):
                    logger.error(f"Missing required config section: {section}")
                    return False
            
            logger.info("Configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation error: {e}")
            return False
    
    def reload_config(self):
        """Reload configuration from files"""
        try:
            self._load_environment()
            self._load_yaml_config()
            logger.info("Configuration reloaded")
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")
    
    def update_setting(self, key: str, value: Any):
        """
        Update a configuration setting (in memory only)
        
        Args:
            key: Configuration key (supports dot notation)
            value: New value
        """
        try:
            keys = key.split('.')
            config = self.config_data
            
            # Navigate to the parent of the target key
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            
            # Set the value
            config[keys[-1]] = value
            logger.debug(f"Updated setting '{key}' = {value}")
            
        except Exception as e:
            logger.error(f"Error updating setting '{key}': {e}")
    
    def save_config_to_file(self, output_file: str = None):
        """
        Save current configuration to YAML file
        
        Args:
            output_file: Output file path (defaults to current config file)
        """
        try:
            output_file = output_file or self.config_file
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as file:
                yaml.dump(self.config_data, file, default_flow_style=False, indent=2)
            
            logger.info(f"Configuration saved to {output_file}")
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        Get configuration summary for debugging
        
        Returns:
            Dict containing configuration summary
        """
        try:
            return {
                "env_file": self.env_file,
                "config_file": self.config_file,
                "config_sections": list(self.config_data.keys()),
                "environment_vars_count": len([k for k in os.environ.keys() if not any(s in k.upper() for s in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN'])]),
                "secrets_configured": len([k for k in ['GMAIL_EMAIL', 'SERVICENOW_INSTANCE_URL', 'GROQ_API_KEY'] if self.get_secret(k)]),
                "validation_status": self.validate_config()
            }
        except Exception as e:
            logger.error(f"Error getting config summary: {e}")
            return {"error": str(e)}
    
    def create_sample_env_file(self, output_file: str = ".env.sample"):
        """
        Create a sample .env file with required variables
        
        Args:
            output_file: Output file path
        """
        try:
            sample_content = """# Gmail Configuration
GMAIL_EMAIL=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password

# ServiceNow Configuration  
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password

# GROQ AI Configuration
GROQ_API_KEY=your-groq-api-key

# SMTP Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=support@yourcompany.com

# Optional: Override default SMTP settings
# SMTP_SERVER=your-smtp-server.com
# SMTP_PORT=587
"""
            
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(sample_content)
            
            logger.info(f"Sample environment file created: {output_file}")
            
        except Exception as e:
            logger.error(f"Error creating sample env file: {e}")