#!/usr/bin/env python3
"""
Configuration loader for deployment workflows
This module provides utilities to load and access configuration from YAML files
"""

import os
import sys
import yaml
from typing import Dict, Any, Optional, List

class DeploymentConfig:
    """Configuration loader and accessor for deployment workflows"""
    
    def __init__(self, config_file: str = 'deployment.config.yml'):
        """
        Initialize configuration loader
        
        Args:
            config_file: Path to the configuration YAML file
        """
        self.config_file = config_file
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        # Try to find config file in multiple locations
        possible_paths = [
            self.config_file,
            os.path.join(os.path.dirname(__file__), '..', self.config_file),
            os.path.join(os.getcwd(), self.config_file)
        ]
        
        config_path = None
        for path in possible_paths:
            if os.path.exists(path):
                config_path = path
                break
        
        if not config_path:
            raise FileNotFoundError(f"Configuration file not found. Searched: {possible_paths}")
        
        try:
            with open(config_path, 'r') as file:
                config = yaml.safe_load(file)
                print(f"✅ Configuration loaded from: {config_path}")
                return config
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in configuration file {config_path}: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load configuration from {config_path}: {e}")
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        
        Args:
            key_path: Dot-separated path to the configuration value (e.g., 'aws.region')
            default: Default value if key is not found
            
        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_aws_region(self) -> str:
        """Get AWS region from configuration"""
        return self.get('aws.region', 'us-east-1')
    
    def get_instance_name(self) -> str:
        """Get Lightsail instance name from configuration"""
        return self.get('lightsail.instance_name', 'lamp-stack-demo')
    
    def get_static_ip(self) -> str:
        """Get Lightsail static IP from configuration"""
        return self.get('lightsail.static_ip', '')
    
    def get_php_version(self) -> str:
        """Get PHP version from configuration"""
        return self.get('application.php_version', '8.1')
    
    def get_package_files(self) -> List[str]:
        """Get list of files to include in deployment package"""
        return self.get('application.package_files', ['index.php', 'css/', 'config/'])
    
    def get_package_fallback(self) -> bool:
        """Check if package fallback is enabled"""
        return self.get('application.package_fallback', True)
    
    def get_environment_variables(self) -> Dict[str, str]:
        """Get environment variables to set on the instance"""
        return self.get('application.environment_variables', {})
    
    def get_timeout(self, timeout_type: str) -> int:
        """
        Get timeout value for specific operation
        
        Args:
            timeout_type: Type of timeout (ssh_connection, command_execution, health_check)
        """
        return self.get(f'deployment.timeouts.{timeout_type}', 120)
    
    def get_max_retries(self) -> int:
        """Get maximum retry attempts"""
        return self.get('deployment.retries.max_attempts', 3)
    
    def get_ssh_retries(self) -> int:
        """Get SSH connection retry attempts"""
        return self.get('deployment.retries.ssh_connection', 5)
    
    def is_step_enabled(self, step_path: str) -> bool:
        """
        Check if a deployment step is enabled
        
        Args:
            step_path: Path to the step (e.g., 'pre_deployment.common', 'post_deployment.lamp')
        """
        return self.get(f'deployment.steps.{step_path}.enabled', True)
    
    def get_step_config(self, step_path: str) -> Dict[str, Any]:
        """
        Get configuration for a specific deployment step
        
        Args:
            step_path: Path to the step configuration
        """
        return self.get(f'deployment.steps.{step_path}', {})
    
    def get_health_check_config(self) -> Dict[str, Any]:
        """Get health check configuration"""
        return self.get('monitoring.health_check', {
            'endpoint': '/',
            'expected_content': 'Hello Welcome',
            'max_attempts': 10,
            'wait_between_attempts': 10,
            'initial_wait': 30
        })
    
    def get_github_actions_config(self) -> Dict[str, Any]:
        """Get GitHub Actions configuration"""
        return self.get('github_actions', {})
    
    def get_security_config(self) -> Dict[str, Any]:
        """Get security configuration"""
        return self.get('security', {})
    
    def get_backup_config(self) -> Dict[str, Any]:
        """Get backup configuration"""
        return self.get('backup', {})
    
    def should_deploy_on_branch(self, branch: str, event_type: str) -> bool:
        """
        Check if deployment should happen for given branch and event type
        
        Args:
            branch: Git branch name
            event_type: GitHub event type (push, pull_request, workflow_dispatch)
        """
        if event_type == 'workflow_dispatch':
            return True
        
        if event_type == 'push':
            push_branches = self.get('github_actions.triggers.push_branches', ['main', 'master'])
            deploy_on_push = self.get('github_actions.jobs.deployment.deploy_on_push', True)
            return deploy_on_push and branch in push_branches
        
        if event_type == 'pull_request':
            deploy_on_pr = self.get('github_actions.jobs.deployment.deploy_on_pr', False)
            return deploy_on_pr
        
        return False
    
    def print_config_summary(self):
        """Print a summary of key configuration values"""
        print("📋 Configuration Summary:")
        print(f"  AWS Region: {self.get_aws_region()}")
        print(f"  Instance: {self.get_instance_name()}")
        print(f"  Static IP: {self.get_static_ip()}")
        print(f"  PHP Version: {self.get_php_version()}")
        print(f"  Package Files: {', '.join(self.get_package_files())}")
        print(f"  Environment Variables: {list(self.get_environment_variables().keys())}")
        print(f"  SSH Timeout: {self.get_timeout('ssh_connection')}s")
        print(f"  Max Retries: {self.get_max_retries()}")

def load_deployment_config(config_file: str = 'deployment.config.yml') -> DeploymentConfig:
    """
    Convenience function to load deployment configuration
    
    Args:
        config_file: Path to configuration file
        
    Returns:
        DeploymentConfig instance
    """
    return DeploymentConfig(config_file)

# Alias for backward compatibility
ConfigLoader = DeploymentConfig

# Example usage and testing
if __name__ == '__main__':
    try:
        config = load_deployment_config()
        config.print_config_summary()
        
        # Test some specific configurations
        print("\n🔧 Testing specific configurations:")
        print(f"Pre-deployment common enabled: {config.is_step_enabled('pre_deployment.common')}")
        print(f"LAMP installation enabled: {config.is_step_enabled('pre_deployment.lamp')}")
        print(f"Health check endpoint: {config.get_health_check_config()['endpoint']}")
        
        # Test branch deployment logic
        print(f"Deploy on main push: {config.should_deploy_on_branch('main', 'push')}")
        print(f"Deploy on feature PR: {config.should_deploy_on_branch('feature', 'pull_request')}")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        sys.exit(1)
