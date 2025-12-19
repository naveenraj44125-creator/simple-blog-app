#!/usr/bin/env python3
"""
Operating System Detection Utility for Multi-OS Lightsail Deployments
Detects the operating system and package manager from blueprint information
"""

import re
from typing import Tuple, Dict, Any

class OSDetector:
    """Detects operating system and package manager from Lightsail blueprint"""
    
    # Blueprint patterns for different operating systems
    OS_PATTERNS = {
        'ubuntu': {
            'patterns': [r'ubuntu', r'Ubuntu'],
            'package_manager': 'apt',
            'service_manager': 'systemd',
            'user': 'ubuntu'
        },
        'amazon_linux': {
            'patterns': [r'amazon.*linux', r'amzn', r'Amazon.*Linux'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'ec2-user'
        },
        'centos': {
            'patterns': [r'centos', r'CentOS'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'centos'
        },
        'rhel': {
            'patterns': [r'rhel', r'red.*hat', r'RedHat'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'ec2-user'
        }
    }
    
    @classmethod
    def detect_os_from_blueprint(cls, blueprint_id: str, blueprint_name: str = "") -> Tuple[str, Dict[str, str]]:
        """
        Detect operating system from blueprint information
        
        Args:
            blueprint_id: Lightsail blueprint ID (e.g., 'ubuntu_22_04', 'amazon_linux_2023')
            blueprint_name: Human-readable blueprint name (optional)
            
        Returns:
            Tuple of (os_type, os_info) where os_info contains package_manager, service_manager, user
        """
        # Combine blueprint_id and blueprint_name for pattern matching
        search_text = f"{blueprint_id} {blueprint_name}".lower()
        
        # Try to match against known patterns
        for os_type, os_config in cls.OS_PATTERNS.items():
            for pattern in os_config['patterns']:
                if re.search(pattern, search_text, re.IGNORECASE):
                    return os_type, {
                        'package_manager': os_config['package_manager'],
                        'service_manager': os_config['service_manager'],
                        'user': os_config['user']
                    }
        
        # Default fallback - assume Ubuntu-like system
        return 'unknown', {
            'package_manager': 'apt',
            'service_manager': 'systemd',
            'user': 'ubuntu'
        }
    
    @classmethod
    def get_package_manager_commands(cls, package_manager: str) -> Dict[str, str]:
        """
        Get package manager specific commands
        
        Args:
            package_manager: Package manager type ('apt', 'yum', 'dnf')
            
        Returns:
            Dictionary of command templates
        """
        if package_manager == 'apt':
            return {
                'update': 'sudo apt-get update -qq',
                'install': 'sudo DEBIAN_FRONTEND=noninteractive apt-get install -y',
                'remove': 'sudo apt-get remove -y',
                'search': 'apt-cache search',
                'info': 'apt-cache show',
                'check_installed': 'dpkg -l | grep -q',
                'fix_broken': 'sudo dpkg --configure -a && sudo apt-get install -f -y'
            }
        elif package_manager in ['yum', 'dnf']:
            # Amazon Linux 2023 uses dnf, but yum is aliased to dnf
            # Amazon Linux 2 uses yum
            return {
                'update': 'sudo yum update -y',
                'install': 'sudo yum install -y',
                'remove': 'sudo yum remove -y',
                'search': 'yum search',
                'info': 'yum info',
                'check_installed': 'rpm -q',
                'fix_broken': 'sudo yum clean all && sudo yum makecache'
            }
        else:
            # Fallback to apt commands
            return cls.get_package_manager_commands('apt')
    
    @classmethod
    def get_service_commands(cls, service_manager: str) -> Dict[str, str]:
        """
        Get service manager specific commands
        
        Args:
            service_manager: Service manager type ('systemd', 'sysvinit')
            
        Returns:
            Dictionary of service command templates
        """
        if service_manager == 'systemd':
            return {
                'start': 'sudo systemctl start',
                'stop': 'sudo systemctl stop',
                'restart': 'sudo systemctl restart',
                'enable': 'sudo systemctl enable',
                'disable': 'sudo systemctl disable',
                'status': 'sudo systemctl status',
                'is_active': 'systemctl is-active --quiet',
                'reload': 'sudo systemctl daemon-reload'
            }
        else:
            # Fallback to systemd commands (most modern systems use systemd)
            return cls.get_service_commands('systemd')
    
    @classmethod
    def get_os_specific_packages(cls, os_type: str, package_manager: str) -> Dict[str, Dict[str, str]]:
        """
        Get OS-specific package names for common dependencies
        
        Args:
            os_type: Operating system type
            package_manager: Package manager type
            
        Returns:
            Dictionary mapping generic package names to OS-specific package names
        """
        if package_manager == 'apt':
            return {
                'apache': {'packages': ['apache2'], 'service': 'apache2'},
                'nginx': {'packages': ['nginx'], 'service': 'nginx'},
                'mysql_server': {'packages': ['mysql-server'], 'service': 'mysql'},
                'mysql_client': {'packages': ['mysql-client'], 'service': None},
                'postgresql_server': {'packages': ['postgresql', 'postgresql-contrib'], 'service': 'postgresql'},
                'postgresql_client': {'packages': ['postgresql-client'], 'service': None},
                'php': {'packages': ['php', 'php-fpm'], 'service': 'php8.1-fpm'},
                'python': {'packages': ['python3', 'python3-pip', 'python3-venv'], 'service': None},
                'nodejs': {'packages': [], 'service': None},  # Installed via NodeSource
                'redis': {'packages': ['redis-server'], 'service': 'redis-server'},
                'git': {'packages': ['git'], 'service': None},
                'curl': {'packages': ['curl'], 'service': None},
                'wget': {'packages': ['wget'], 'service': None},
                'unzip': {'packages': ['unzip'], 'service': None},
                'firewall': {'packages': ['ufw'], 'service': 'ufw'}
            }
        elif package_manager in ['yum', 'dnf']:
            return {
                'apache': {'packages': ['httpd'], 'service': 'httpd'},
                'nginx': {'packages': ['nginx'], 'service': 'nginx'},
                'mysql_server': {'packages': ['mysql-server'], 'service': 'mysqld'},
                'mysql_client': {'packages': ['mysql'], 'service': None},
                'postgresql_server': {'packages': ['postgresql-server', 'postgresql-contrib'], 'service': 'postgresql'},
                'postgresql_client': {'packages': ['postgresql'], 'service': None},
                'php': {'packages': ['php', 'php-fpm'], 'service': 'php-fpm'},
                'python': {'packages': ['python3', 'python3-pip'], 'service': None},
                'nodejs': {'packages': [], 'service': None},  # Installed via NodeSource
                'redis': {'packages': ['redis'], 'service': 'redis'},
                'git': {'packages': ['git'], 'service': None},
                'curl': {'packages': ['curl'], 'service': None},
                'wget': {'packages': ['wget'], 'service': None},
                'unzip': {'packages': ['unzip'], 'service': None},
                'firewall': {'packages': ['firewalld'], 'service': 'firewalld'}
            }
        else:
            # Fallback to apt packages
            return cls.get_os_specific_packages('ubuntu', 'apt')

    @classmethod
    def get_user_info(cls, os_type: str) -> Dict[str, str]:
        """
        Get OS-specific user information
        
        Args:
            os_type: Operating system type
            
        Returns:
            Dictionary with user information
        """
        user_configs = {
            'ubuntu': {
                'default_user': 'ubuntu',
                'web_user': 'www-data',
                'web_group': 'www-data',
                'nginx_user': 'www-data',
                'nginx_group': 'www-data',
                'apache_user': 'www-data',
                'apache_group': 'www-data'
            },
            'amazon_linux': {
                'default_user': 'ec2-user',
                'web_user': 'nginx',  # Use nginx user for web apps on Amazon Linux
                'web_group': 'nginx',
                'nginx_user': 'nginx',
                'nginx_group': 'nginx',
                'apache_user': 'apache',  # Only available after httpd installation
                'apache_group': 'apache'
            },
            'centos': {
                'default_user': 'centos',
                'web_user': 'nginx',  # Use nginx user for web apps on CentOS
                'web_group': 'nginx',
                'nginx_user': 'nginx',
                'nginx_group': 'nginx',
                'apache_user': 'apache',
                'apache_group': 'apache'
            },
            'rhel': {
                'default_user': 'ec2-user',
                'web_user': 'nginx',  # Use nginx user for web apps on RHEL
                'web_group': 'nginx',
                'nginx_user': 'nginx',
                'nginx_group': 'nginx',
                'apache_user': 'apache',
                'apache_group': 'apache'
            }
        }
        
        return user_configs.get(os_type, user_configs['ubuntu'])

if __name__ == "__main__":
    # Test the OS detector
    test_cases = [
        ("ubuntu_22_04", "Ubuntu 22.04 LTS"),
        ("amazon_linux_2023", "Amazon Linux 2023"),
        ("amazon_linux_2", "Amazon Linux 2"),
        ("centos_7_2009_01", "CentOS 7"),
        ("unknown_blueprint", "Unknown OS")
    ]
    
    for blueprint_id, blueprint_name in test_cases:
        os_type, os_info = OSDetector.detect_os_from_blueprint(blueprint_id, blueprint_name)
        print(f"Blueprint: {blueprint_id} -> OS: {os_type}, Package Manager: {os_info['package_manager']}")