#!/usr/bin/env python3
"""
Generic Dependency Manager for AWS Lightsail Deployments
This module handles installation and configuration of various dependencies
based on configuration settings (Apache, MySQL, PHP, Python, Node.js, etc.)
Supports multiple operating systems: Ubuntu, Amazon Linux, CentOS, RHEL
"""

import sys
import json
from typing import Dict, List, Any, Tuple
from config_loader import DeploymentConfig
from lightsail_rds import LightsailRDSManager
from os_detector import OSDetector

class DependencyManager:
    """Manages installation and configuration of application dependencies"""
    
    def __init__(self, lightsail_client, config: DeploymentConfig, os_type: str = None, os_info: Dict[str, str] = None):
        """
        Initialize dependency manager
        
        Args:
            lightsail_client: Lightsail client instance for running commands
            config: Deployment configuration instance
            os_type: Operating system type (ubuntu, amazon_linux, centos, rhel)
            os_info: OS information dict with package_manager, service_manager, user
        """
        self.client = lightsail_client
        self.config = config
        self.installed_dependencies = []
        self.failed_dependencies = []
        
        # Set OS information
        self.os_type = os_type or 'ubuntu'
        self.os_info = os_info or {'package_manager': 'apt', 'service_manager': 'systemd', 'user': 'ubuntu'}
        
        # Get OS-specific command templates
        self.pkg_commands = OSDetector.get_package_manager_commands(self.os_info['package_manager'])
        self.svc_commands = OSDetector.get_service_commands(self.os_info['service_manager'])
        self.os_packages = OSDetector.get_os_specific_packages(self.os_type, self.os_info['package_manager'])
        self.user_info = OSDetector.get_user_info(self.os_type)
        
        print(f"🖥️  Detected OS: {self.os_type} with {self.os_info['package_manager']} package manager")
    
    def get_enabled_dependencies(self) -> List[str]:
        """Get list of enabled dependencies from configuration"""
        dependencies = []
        deps_config = self.config.get('dependencies', {})
        
        for dep_name, dep_config in deps_config.items():
            if isinstance(dep_config, dict) and dep_config.get('enabled', False):
                dependencies.append(dep_name)
        
        return dependencies
    
    def install_all_dependencies(self) -> Tuple[bool, List[str], List[str]]:
        """
        Install all enabled dependencies
        
        Returns:
            Tuple of (success, installed_deps, failed_deps)
        """
        enabled_deps = self.get_enabled_dependencies()
        
        if not enabled_deps:
            print("ℹ️  No dependencies enabled in configuration")
            return True, [], []
        
        print(f"📦 Installing {len(enabled_deps)} enabled dependencies: {', '.join(enabled_deps)}")
        
        # First, check and fix package manager if it's in a broken state
        print(f"\n🔧 Checking {self.os_info['package_manager']} state...")
        if self.os_info['package_manager'] == 'apt':
            fix_script = '''
# Check if dpkg is in a broken state
if sudo dpkg --audit 2>&1 | grep -q "broken"; then
    echo "⚠️  dpkg is in a broken state, fixing..."
    sudo dpkg --configure -a
    sudo apt-get install -f -y
    echo "✅ dpkg fixed"
else
    echo "✅ dpkg is healthy"
fi
'''
        else:
            # For yum/dnf systems
            fix_script = f'''
# Clean package manager cache and check for issues
echo "Cleaning {self.os_info['package_manager']} cache..."
{self.pkg_commands['fix_broken']}
echo "✅ Package manager state verified"
'''
        
        success, output = self.client.run_command(fix_script, timeout=180)
        if not success:
            print(f"⚠️  {self.os_info['package_manager']} check/fix failed, but continuing...")
        else:
            print(f"✅ {self.os_info['package_manager']} state verified")
        
        # Update package lists/cache
        print(f"\n🔄 Updating package lists using {self.os_info['package_manager']}...")
        if self.os_info['package_manager'] == 'apt':
            update_script = '''
set -e
echo "Running apt-get update..."
# Use faster update with reduced timeout for GitHub Actions
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq -o Acquire::Retries=2 -o Acquire::http::Timeout=30
echo "✅ Package lists updated"
'''
        else:
            # For yum/dnf systems
            update_script = f'''
set -e
echo "Running {self.os_info['package_manager']} update..."
{self.pkg_commands['update']}
echo "✅ Package cache updated"
'''
        
        success, output = self.client.run_command(update_script, timeout=180)
        if not success:
            print(f"⚠️  {self.os_info['package_manager']} update failed, but continuing with installations...")
        else:
            print("✅ Package lists updated successfully")
        
        # Install dependencies in order of priority
        dependency_order = [
            'git', 'firewall', 'apache', 'nginx', 'mysql', 'postgresql', 
            'php', 'python', 'nodejs', 'redis', 'memcached', 'docker',
            'ssl_certificates', 'monitoring'
        ]
        
        # Sort enabled dependencies by priority order
        sorted_deps = []
        for dep in dependency_order:
            if dep in enabled_deps:
                sorted_deps.append(dep)
        
        # Add any remaining dependencies not in the priority list
        for dep in enabled_deps:
            if dep not in sorted_deps:
                sorted_deps.append(dep)
        
        overall_success = True
        
        # Batch install common system packages first for efficiency
        self._batch_install_common_packages(sorted_deps)
        
        for dep_name in sorted_deps:
            print(f"\n🔧 Installing {dep_name}...")
            success = self._install_dependency(dep_name)
            
            if success:
                self.installed_dependencies.append(dep_name)
                print(f"✅ {dep_name} installed successfully")
            else:
                self.failed_dependencies.append(dep_name)
                print(f"❌ {dep_name} installation failed")
                overall_success = False
        
        return overall_success, self.installed_dependencies, self.failed_dependencies
    
    def _batch_install_common_packages(self, enabled_deps: List[str]):
        """Batch install common system packages for efficiency"""
        common_packages = []
        
        # Collect common packages needed by multiple dependencies (OS-agnostic names)
        if any(dep in enabled_deps for dep in ['apache', 'nginx', 'php']):
            common_packages.extend(['curl', 'wget', 'unzip'])
        
        if 'git' in enabled_deps:
            common_packages.append('git')
        
        if 'nodejs' in enabled_deps:
            common_packages.append('curl')
            # Add OS-specific packages for Node.js setup
            if self.os_info['package_manager'] == 'apt':
                common_packages.append('software-properties-common')
        
        if 'python' in enabled_deps:
            if self.os_info['package_manager'] == 'apt':
                common_packages.extend(['python3', 'python3-pip', 'python3-venv'])
            else:
                common_packages.extend(['python3', 'python3-pip'])
        
        if 'php' in enabled_deps and self.os_info['package_manager'] == 'apt':
            common_packages.append('software-properties-common')
        
        # Remove duplicates and install in batch
        if common_packages:
            unique_packages = list(set(common_packages))
            print(f"\n📦 Batch installing common packages: {', '.join(unique_packages)}")
            
            if self.os_info['package_manager'] == 'apt':
                batch_script = f'''
set -e
export DEBIAN_FRONTEND=noninteractive
echo "Installing common packages in batch for efficiency..."
{self.pkg_commands['install']} {' '.join(unique_packages)}
echo "✅ Common packages installed"
'''
            else:
                batch_script = f'''
set -e
echo "Installing common packages in batch for efficiency..."
{self.pkg_commands['install']} {' '.join(unique_packages)}
echo "✅ Common packages installed"
'''
            
            success, output = self.client.run_command(batch_script, timeout=300)
            if success:
                print("✅ Batch installation completed successfully")
            else:
                print("⚠️  Batch installation had issues, individual installs will proceed")
    
    def _is_dependency_installed(self, dep_name: str) -> bool:
        """Quick check if a dependency is already installed (OS-agnostic)"""
        # Get OS-specific service names
        apache_service = self.os_packages.get('apache', {}).get('service', 'apache2')
        redis_service = self.os_packages.get('redis', {}).get('service', 'redis-server')
        
        check_commands = {
            'apache': f'{self.svc_commands["is_active"]} {apache_service}',
            'nginx': f'{self.svc_commands["is_active"]} nginx',
            'mysql': 'command -v mysql >/dev/null 2>&1',
            'postgresql': 'command -v psql >/dev/null 2>&1',
            'php': 'command -v php >/dev/null 2>&1',
            'python': 'command -v python3 >/dev/null 2>&1',
            'nodejs': 'command -v node >/dev/null 2>&1',
            'redis': f'{self.svc_commands["is_active"]} {redis_service} || {self.svc_commands["is_active"]} redis',
            'git': 'command -v git >/dev/null 2>&1',
            'docker': 'command -v docker >/dev/null 2>&1'
        }
        
        if dep_name not in check_commands:
            return False
        
        success, _ = self.client.run_command(check_commands[dep_name], timeout=10, max_retries=1)
        return success
    
    def _wait_for_package_lock(self, timeout=60):
        """Wait for package manager lock to be released (OS-agnostic)"""
        if self.os_info['package_manager'] == 'apt':
            wait_script = '''
# Quick check for dpkg lock
if ! sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 && ! sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1; then
    echo "✅ dpkg lock is available"
    exit 0
fi

# Wait for lock to be released
echo "⏳ Waiting for dpkg lock (max 60s)..."
timeout=60
elapsed=0
while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1; do
    if [ $elapsed -ge $timeout ]; then
        echo "⚠️  dpkg still locked after ${timeout}s, proceeding anyway..."
        # Kill any stuck apt processes
        sudo killall apt apt-get dpkg 2>/dev/null || true
        sleep 2
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    [ $((elapsed % 10)) -eq 0 ] && echo "   Still waiting... (${elapsed}s)"
done
echo "✅ Proceeding with installation"
'''
        else:
            # For yum/dnf systems, check for yum lock
            wait_script = f'''
# Quick check for yum lock
if ! sudo fuser /var/run/yum.pid >/dev/null 2>&1; then
    echo "✅ {self.os_info['package_manager']} lock is available"
    exit 0
fi

# Wait for lock to be released
echo "⏳ Waiting for {self.os_info['package_manager']} lock (max 60s)..."
timeout=60
elapsed=0
while sudo fuser /var/run/yum.pid >/dev/null 2>&1; do
    if [ $elapsed -ge $timeout ]; then
        echo "⚠️  {self.os_info['package_manager']} still locked after ${{timeout}}s, proceeding anyway..."
        # Kill any stuck yum processes
        sudo killall yum dnf 2>/dev/null || true
        sleep 2
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    [ $((elapsed % 10)) -eq 0 ] && echo "   Still waiting... (${{elapsed}}s)"
done
echo "✅ Proceeding with installation"
'''
        
        self.client.run_command(wait_script, timeout=timeout + 10)
    
    def _install_dependency(self, dep_name: str) -> bool:
        """Install a specific dependency with retry logic"""
        dep_config = self.config.get(f'dependencies.{dep_name}', {})
        
        # Wait for any existing package manager locks before starting
        self._wait_for_package_lock()
        
        # Try installation with retry on failure
        max_retries = 2
        for attempt in range(max_retries):
            if attempt > 0:
                print(f"🔄 Retry attempt {attempt + 1}/{max_retries} for {dep_name}...")
                # On retry, wait for locks and try to fix package manager
                self._wait_for_package_lock()
                fix_script = self.pkg_commands['fix_broken']
                self.client.run_command(fix_script, timeout=60)
            
            success = self._do_install_dependency(dep_name, dep_config)
            if success:
                return True
            
            if attempt < max_retries - 1:
                print(f"⚠️  Installation failed, will retry...")
        
        return False
    
    def _do_install_dependency(self, dep_name: str, dep_config: dict) -> bool:
        """Perform the actual dependency installation"""
        
        # Quick check if dependency is already installed (optimization)
        if self._is_dependency_installed(dep_name):
            print(f"✅ {dep_name} is already installed, skipping...")
            return True

        # Check if this is an external RDS database
        if dep_name in ['mysql', 'postgresql'] and dep_config.get('external', False):
            return self._install_external_database(dep_name, dep_config)

        if dep_name == 'apache':
            return self._install_apache(dep_config)
        elif dep_name == 'nginx':
            return self._install_nginx(dep_config)
        elif dep_name == 'mysql':
            return self._install_mysql(dep_config)
        elif dep_name == 'postgresql':
            return self._install_postgresql(dep_config)
        elif dep_name == 'php':
            return self._install_php(dep_config)
        elif dep_name == 'python':
            return self._install_python(dep_config)
        elif dep_name == 'nodejs':
            return self._install_nodejs(dep_config)
        elif dep_name == 'redis':
            return self._install_redis(dep_config)
        elif dep_name == 'memcached':
            return self._install_memcached(dep_config)
        elif dep_name == 'docker':
            return self._install_docker(dep_config)
        elif dep_name == 'git':
            return self._install_git(dep_config)
        elif dep_name == 'firewall':
            return self._configure_firewall(dep_config)
        elif dep_name == 'ssl_certificates':
            return self._install_ssl_certificates(dep_config)
        elif dep_name == 'monitoring':
            return self._install_monitoring_tools(dep_config)
        else:
            print(f"⚠️  Unknown dependency: {dep_name}")
            return False
    
    def _install_apache(self, config: Dict[str, Any]) -> bool:
        """Install and configure Apache web server (OS-agnostic)"""
        version = config.get('version', 'latest')
        apache_config = config.get('config', {})
        document_root = apache_config.get('document_root', '/var/www/html')
        
        # Get OS-specific package and service names
        apache_packages = self.os_packages.get('apache', {}).get('packages', ['apache2'])
        apache_service = self.os_packages.get('apache', {}).get('service', 'apache2')
        web_user = self.user_info['web_user']
        web_group = self.user_info['web_group']
        
        print(f"🔧 Installing Apache web server on {self.os_type}...")
        
        # Step 1: Install Apache
        print(f"\n📦 Step 1: Installing Apache packages: {', '.join(apache_packages)}")
        install_cmd = f"{self.pkg_commands['install']} {' '.join(apache_packages)}"
        success, output = self.client.run_command(install_cmd)
        if not success:
            return False
        
        # Step 2: Enable Apache service
        print(f"\n🔧 Step 2: Enabling Apache service ({apache_service})")
        enable_cmd = f"{self.svc_commands['enable']} {apache_service}"
        success, output = self.client.run_command(enable_cmd)
        if not success:
            return False
        
        # Step 3: Create document root
        print(f"\n📁 Step 3: Creating document root: {document_root}")
        success, output = self.client.run_command(f"sudo mkdir -p {document_root}")
        if not success:
            return False
        
        # Step 4: Set ownership
        print(f"\n🔐 Step 4: Setting proper ownership ({web_user}:{web_group})")
        success, output = self.client.run_command(f"sudo chown -R {web_user}:{web_group} {document_root}")
        if not success:
            return False
        
        # Step 5: Set permissions
        print("\n🔐 Step 5: Setting proper permissions")
        success, output = self.client.run_command(f"sudo chmod -R 755 {document_root}")
        if not success:
            return False
        
        # Step 6: Enable mod_rewrite if requested (Ubuntu/Debian specific)
        if apache_config.get('enable_rewrite', True) and self.os_info['package_manager'] == 'apt':
            print("\n🔧 Step 6: Enabling mod_rewrite")
            success, output = self.client.run_command("sudo a2enmod rewrite")
            if not success:
                print("⚠️  mod_rewrite enable failed, but continuing...")
        
        # Step 7: Configure security settings (if config files exist)
        if config.get('hide_version', True):
            print("\n🔒 Step 7: Configuring security settings")
            if self.os_info['package_manager'] == 'apt':
                # Ubuntu/Debian Apache config
                security_script = '''
echo "ServerTokens Prod" | sudo tee -a /etc/apache2/conf-available/security.conf
echo "ServerSignature Off" | sudo tee -a /etc/apache2/conf-available/security.conf
sudo a2enconf security 2>/dev/null || true
'''
            else:
                # RHEL/CentOS/Amazon Linux Apache config
                security_script = '''
echo "ServerTokens Prod" | sudo tee -a /etc/httpd/conf/httpd.conf
echo "ServerSignature Off" | sudo tee -a /etc/httpd/conf/httpd.conf
'''
            
            success, output = self.client.run_command(security_script)
            if not success:
                print("⚠️  Security configuration failed, but continuing...")
        
        # Step 8: Start Apache
        print(f"\n🚀 Step 8: Starting Apache service ({apache_service})")
        start_cmd = f"{self.svc_commands['start']} {apache_service}"
        success, output = self.client.run_command(start_cmd)
        if not success:
            return False
        
        # Step 9: Reload Apache
        print(f"\n🔄 Step 9: Reloading Apache configuration")
        reload_cmd = f"{self.svc_commands['restart']} {apache_service}"
        success, output = self.client.run_command(reload_cmd)
        if not success:
            return False
        
        print(f"\n✅ Apache installation completed successfully on {self.os_type}!")
        return True
    
    def _install_nginx(self, config: Dict[str, Any]) -> bool:
        """Install and configure Nginx web server (OS-agnostic)"""
        nginx_config = config.get('config', {})
        document_root = nginx_config.get('document_root', '/var/www/html')
        
        # Get OS-specific package and service names
        nginx_packages = self.os_packages.get('nginx', {}).get('packages', ['nginx'])
        nginx_service = self.os_packages.get('nginx', {}).get('service', 'nginx')
        web_user = self.user_info['web_user']
        web_group = self.user_info['web_group']
        
        script = f'''
set -e
echo "Installing Nginx web server on {self.os_type}..."

# Install Nginx
{self.pkg_commands['install']} {' '.join(nginx_packages)}

# Enable Nginx to start on boot
{self.svc_commands['enable']} {nginx_service}

# Configure document root
DOCUMENT_ROOT="{document_root}"
sudo mkdir -p "$DOCUMENT_ROOT"
sudo chown -R {web_user}:{web_group} "$DOCUMENT_ROOT"
sudo chmod -R 755 "$DOCUMENT_ROOT"

# Start Nginx
{self.svc_commands['start']} {nginx_service}

echo "✅ Nginx installation completed on {self.os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _install_mysql(self, config: Dict[str, Any]) -> bool:
        """Install and configure MySQL database (local only, not for external RDS) - OS-agnostic"""
        # This method should only be called for local MySQL installations
        # External databases are handled by _install_external_database
        
        mysql_config = config.get('config', {})
        
        # Get OS-specific package and service names
        mysql_packages = self.os_packages.get('mysql_server', {}).get('packages', ['mysql-server'])
        mysql_service = self.os_packages.get('mysql_server', {}).get('service', 'mysql')
        
        print(f"📦 Installing local MySQL database server on {self.os_type}...")
        print("⚠️  Note: For external RDS databases, only the MySQL client will be installed")
        
        if self.os_info['package_manager'] == 'apt':
            script = f'''
set -e
echo "Installing MySQL database server on Ubuntu/Debian..."

# Set non-interactive mode
export DEBIAN_FRONTEND=noninteractive

# Install MySQL
{self.pkg_commands['install']} {' '.join(mysql_packages)}

# Enable MySQL to start on boot
{self.svc_commands['enable']} {mysql_service}

# Start MySQL
{self.svc_commands['start']} {mysql_service}

# Secure MySQL installation (basic)
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root123';" || true

# Create application database if requested
if [ "{mysql_config.get('create_app_database', True)}" = "True" ]; then
    DB_NAME="{mysql_config.get('database_name', 'app_db')}"
    sudo mysql -u root -proot123 -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;" || true
    echo "✅ Database '$DB_NAME' created"
fi

echo "✅ MySQL installation completed on Ubuntu/Debian"
'''
        else:
            # For RHEL/CentOS/Amazon Linux
            script = f'''
set -e
echo "Installing MySQL database server on RHEL/CentOS/Amazon Linux..."

# Install MySQL
{self.pkg_commands['install']} {' '.join(mysql_packages)}

# Enable MySQL to start on boot
{self.svc_commands['enable']} {mysql_service}

# Start MySQL
{self.svc_commands['start']} {mysql_service}

# Secure MySQL installation (basic) - different service name on RHEL systems
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root123';" || true

# Create application database if requested
if [ "{mysql_config.get('create_app_database', True)}" = "True" ]; then
    DB_NAME="{mysql_config.get('database_name', 'app_db')}"
    sudo mysql -u root -proot123 -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;" || true
    echo "✅ Database '$DB_NAME' created"
fi

echo "✅ MySQL installation completed on RHEL/CentOS/Amazon Linux"
'''
        
        success, output = self.client.run_command_with_live_output(script, timeout=300)
        return success
    
    def _install_postgresql(self, config: Dict[str, Any]) -> bool:
        """Install and configure PostgreSQL database (local only, not for external RDS) - OS-agnostic"""
        # This method should only be called for local PostgreSQL installations
        # External databases are handled by _install_external_database
        
        pg_config = config.get('config', {})
        
        # Get OS-specific package and service names
        pg_packages = self.os_packages.get('postgresql_server', {}).get('packages', ['postgresql', 'postgresql-contrib'])
        pg_service = self.os_packages.get('postgresql_server', {}).get('service', 'postgresql')
        
        print(f"📦 Installing local PostgreSQL database server on {self.os_type}...")
        print("⚠️  Note: For external RDS databases, only the PostgreSQL client will be installed")
        
        script = f'''
set -e
echo "Installing PostgreSQL database server on {self.os_type}..."

# Install PostgreSQL
{self.pkg_commands['install']} {' '.join(pg_packages)}

# Enable PostgreSQL to start on boot
{self.svc_commands['enable']} {pg_service}

# Start PostgreSQL
{self.svc_commands['start']} {pg_service}

# Create application database if requested
if [ "{pg_config.get('create_app_database', True)}" = "True" ]; then
    DB_NAME="{pg_config.get('database_name', 'app_db')}"
    sudo -u postgres createdb "$DB_NAME" || true
    echo "✅ Database '$DB_NAME' created"
fi

echo "✅ PostgreSQL installation completed on {self.os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=300)
        return success
    
    def _install_php(self, config: Dict[str, Any]) -> bool:
        """Install and configure PHP (OS-agnostic)"""
        version = config.get('version', '8.1')
        php_config = config.get('config', {})
        extensions = php_config.get('extensions', ['pdo', 'pdo_mysql'])
        
        # Get OS-specific package and service names
        php_packages = self.os_packages.get('php', {}).get('packages', ['php', 'php-fpm'])
        php_service = self.os_packages.get('php', {}).get('service', 'php8.1-fpm')
        apache_service = self.os_packages.get('apache', {}).get('service', 'apache2')
        
        # Build extension list based on OS
        ext_packages = []
        for ext in extensions:
            # Skip 'pdo' as it's built into PHP (part of php-common)
            if ext == 'pdo':
                continue  # PDO is included in php-common, no separate package
            elif ext == 'pdo_mysql' or ext == 'mysql':
                if self.os_info['package_manager'] == 'apt':
                    ext_packages.extend(['php-mysql', f'php{version}-mysql'])
                else:
                    ext_packages.append('php-mysqlnd')
            elif ext == 'pdo_pgsql' or ext == 'pgsql':
                if self.os_info['package_manager'] == 'apt':
                    ext_packages.extend(['php-pgsql', f'php{version}-pgsql'])
                else:
                    ext_packages.append('php-pgsql')
            elif ext == 'redis':
                if self.os_info['package_manager'] == 'apt':
                    ext_packages.extend(['php-redis', f'php{version}-redis'])
                else:
                    ext_packages.append('php-redis')
            elif ext == 'json':
                continue  # JSON is built into PHP 8.0+, no separate package needed
            else:
                if self.os_info['package_manager'] == 'apt':
                    ext_packages.append(f'php-{ext}')
                else:
                    ext_packages.append(f'php-{ext}')
        
        ext_list = ' '.join(ext_packages) if ext_packages else ''
        
        if self.os_info['package_manager'] == 'apt':
            script = f'''
set -e
echo "Installing PHP {version} on Ubuntu/Debian..."

# Add Ondrej PPA for PHP (required for PHP 8.1+ on Ubuntu 22.04)
if ! grep -q "ondrej/php" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; then
    echo "Adding Ondrej PHP PPA..."
    {self.pkg_commands['install']} software-properties-common
    sudo add-apt-repository -y ppa:ondrej/php
    {self.pkg_commands['update']}
    echo "✅ Ondrej PHP PPA added"
else
    echo "✅ Ondrej PHP PPA already present"
fi

# Install PHP and extensions
{self.pkg_commands['install']} php{version} php{version}-fpm {ext_list}

# Install Composer if requested
if [ "{php_config.get('enable_composer', True)}" = "True" ]; then
    curl -sS https://getcomposer.org/installer | php
    sudo mv composer.phar /usr/local/bin/composer
    sudo chmod +x /usr/local/bin/composer
    echo "✅ Composer installed"
fi

# Configure PHP-FPM if Apache is also enabled
if {self.svc_commands['is_active']} {apache_service}; then
    {self.pkg_commands['install']} libapache2-mod-php{version}
    sudo a2enmod php{version}
    {self.svc_commands['reload']} {apache_service}
fi

echo "✅ PHP {version} installation completed on Ubuntu/Debian"
'''
        else:
            # For RHEL/CentOS/Amazon Linux
            script = f'''
set -e
echo "Installing PHP {version} on RHEL/CentOS/Amazon Linux..."

# Enable EPEL and Remi repositories for PHP
if ! rpm -q epel-release >/dev/null 2>&1; then
    {self.pkg_commands['install']} epel-release
fi

# Install PHP and extensions
{self.pkg_commands['install']} php php-fpm {ext_list}

# Install Composer if requested
if [ "{php_config.get('enable_composer', True)}" = "True" ]; then
    curl -sS https://getcomposer.org/installer | php
    sudo mv composer.phar /usr/local/bin/composer
    sudo chmod +x /usr/local/bin/composer
    echo "✅ Composer installed"
fi

# Configure PHP-FPM if Apache is also enabled
if {self.svc_commands['is_active']} {apache_service}; then
    {self.svc_commands['restart']} {apache_service}
fi

echo "✅ PHP installation completed on RHEL/CentOS/Amazon Linux"
'''
        
        success, output = self.client.run_command(script, timeout=300)
        return success
    
    def _install_python(self, config: Dict[str, Any]) -> bool:
        """Install and configure Python (OS-agnostic)"""
        version = config.get('version', '3.9')
        python_config = config.get('config', {})
        
        # Get OS-specific package names
        python_packages = self.os_packages.get('python', {}).get('packages', ['python3', 'python3-pip'])
        web_user = self.user_info['web_user']
        web_group = self.user_info['web_group']
        
        if self.os_info['package_manager'] == 'apt':
            script = f'''
set -e
echo "Installing Python {version} on Ubuntu/Debian..."

# Install Python and pip
# For Ubuntu 22.04, python3 is already installed, just install additional tools
if [ "{version}" = "3.10" ] || [ "{version}" = "3" ]; then
    # Use system Python3 - install version-specific venv package
    {self.pkg_commands['install']} python3 python3-pip python3-dev python3.10-venv
else
    # Try to install specific version
    {self.pkg_commands['install']} python{version} python{version}-pip python{version}-venv python{version}-dev || {{
        echo "⚠️  Python {version} not available, using system python3"
        {self.pkg_commands['install']} python3 python3-pip python3-dev python3.10-venv
    }}
fi

# Create virtual environment if requested
if [ "{python_config.get('virtual_env', True)}" = "True" ]; then
    sudo mkdir -p /opt/python-venv
    if [ "{version}" = "3.10" ] || [ "{version}" = "3" ]; then
        sudo python3 -m venv /opt/python-venv/app
    else
        sudo python{version} -m venv /opt/python-venv/app || sudo python3 -m venv /opt/python-venv/app
    fi
    sudo chown -R {web_user}:{web_group} /opt/python-venv
    echo "✅ Python virtual environment created"
fi

echo "✅ Python {version} installation completed on Ubuntu/Debian"
'''
        else:
            # For RHEL/CentOS/Amazon Linux
            script = f'''
set -e
echo "Installing Python {version} on RHEL/CentOS/Amazon Linux..."

# Install Python and pip
{self.pkg_commands['install']} {' '.join(python_packages)}

# Create virtual environment if requested
if [ "{python_config.get('virtual_env', True)}" = "True" ]; then
    sudo mkdir -p /opt/python-venv
    sudo python3 -m venv /opt/python-venv/app
    sudo chown -R {web_user}:{web_group} /opt/python-venv
    echo "✅ Python virtual environment created"
fi

echo "✅ Python installation completed on RHEL/CentOS/Amazon Linux"
'''
        
        success, output = self.client.run_command(script, timeout=300)
        
        # Install pip packages if specified
        pip_packages = python_config.get('pip_packages', [])
        if pip_packages and success:
            pip_script = f'''
set -e
echo "Installing Python packages: {' '.join(pip_packages)}"

if [ -d "/opt/python-venv/app" ]; then
    source /opt/python-venv/app/bin/activate
    pip install --upgrade pip
    pip install {' '.join(pip_packages)}
else
    if [ "{version}" = "3.10" ] || [ "{version}" = "3" ]; then
        sudo pip3 install {' '.join(pip_packages)}
    else
        sudo pip{version} install {' '.join(pip_packages)} || sudo pip3 install {' '.join(pip_packages)}
    fi
fi

echo "✅ Python packages installed"
'''
            success, output = self.client.run_command(pip_script, timeout=420)
        
        return success
    
    def _install_nodejs(self, config: Dict[str, Any]) -> bool:
        """Install and configure Node.js (OS-agnostic)"""
        version = config.get('version', '18')
        node_config = config.get('config', {})
        
        if self.os_info['package_manager'] == 'apt':
            script = f'''
set -e
echo "Installing Node.js {version} on Ubuntu/Debian..."

# Install Node.js via NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_{version}.x | sudo -E bash -
{self.pkg_commands['install']} nodejs

# Install Yarn if requested
if [ "{node_config.get('package_manager', 'npm')}" = "yarn" ]; then
    curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | sudo apt-key add -
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | sudo tee /etc/apt/sources.list.d/yarn.list
    {self.pkg_commands['update']}
    {self.pkg_commands['install']} yarn
fi

echo "✅ Node.js {version} installation completed on Ubuntu/Debian"
'''
        else:
            # For RHEL/CentOS/Amazon Linux
            script = f'''
set -e
echo "Installing Node.js {version} on RHEL/CentOS/Amazon Linux..."

# Install Node.js via NodeSource repository
curl -fsSL https://rpm.nodesource.com/setup_{version}.x | sudo bash -
{self.pkg_commands['install']} nodejs

# Install Yarn if requested
if [ "{node_config.get('package_manager', 'npm')}" = "yarn" ]; then
    curl -sL https://dl.yarnpkg.com/rpm/yarn.repo | sudo tee /etc/yum.repos.d/yarn.repo
    {self.pkg_commands['install']} yarn
fi

echo "✅ Node.js {version} installation completed on RHEL/CentOS/Amazon Linux"
'''
        
        success, output = self.client.run_command(script, timeout=300)
        
        # Install npm packages if specified
        npm_packages = node_config.get('npm_packages', [])
        if npm_packages and success:
            pkg_manager = node_config.get('package_manager', 'npm')
            npm_script = f'''
set -e
echo "Installing Node.js packages: {' '.join(npm_packages)}"
sudo {pkg_manager} install -g {' '.join(npm_packages)}
echo "✅ Node.js packages installed"
'''
            success, output = self.client.run_command(npm_script, timeout=420)
        
        return success
    
    def _install_redis(self, config: Dict[str, Any]) -> bool:
        """Install and configure Redis (OS-agnostic)"""
        # Get OS-specific package and service names
        redis_packages = self.os_packages.get('redis', {}).get('packages', ['redis-server'])
        redis_service = self.os_packages.get('redis', {}).get('service', 'redis-server')
        
        script = f'''
set -e
echo "Installing Redis on {self.os_type}..."

# Install Redis
{self.pkg_commands['install']} {' '.join(redis_packages)}

# Enable Redis to start on boot
{self.svc_commands['enable']} {redis_service}

# Start Redis
{self.svc_commands['start']} {redis_service}

echo "✅ Redis installation completed on {self.os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _install_memcached(self, config: Dict[str, Any]) -> bool:
        """Install and configure Memcached"""
        script = '''
set -e
echo "Installing Memcached..."

# Install Memcached
# sudo apt-get update  # Removed: apt-get update now runs once at start
sudo apt-get install -y memcached

# Enable Memcached to start on boot
sudo systemctl enable memcached

# Start Memcached
sudo systemctl start memcached

echo "✅ Memcached installation completed"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _install_docker(self, config: Dict[str, Any]) -> bool:
        """Install and configure Docker"""
        docker_config = config.get('config', {})
        
        script = f'''
set -e
echo "🐳 Installing Docker (optimized method)..."

# Remove old versions quickly
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install prerequisites (minimal set)
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker GPG key (faster method)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update and install Docker (with compose plugin)
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Verify installation
docker --version
docker compose version

echo "✅ Docker installation completed"
'''
        
        success, output = self.client.run_command(script, timeout=240)
        return success
    
    def _install_git(self, config: Dict[str, Any]) -> bool:
        """Install and configure Git (OS-agnostic)"""
        git_config = config.get('config', {})
        
        # Get OS-specific package names
        git_packages = self.os_packages.get('git', {}).get('packages', ['git'])
        
        script = f'''
set -e
echo "Installing Git on {self.os_type}..."

# Install Git
{self.pkg_commands['install']} {' '.join(git_packages)}

# Install Git LFS if requested (Ubuntu/Debian only for now)
if [ "{git_config.get('install_lfs', False)}" = "True" ] && [ "{self.os_info['package_manager']}" = "apt" ]; then
    curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
    {self.pkg_commands['install']} git-lfs
    echo "✅ Git LFS installed"
fi

echo "✅ Git installation completed on {self.os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _install_awscli(self, config: Dict[str, Any]) -> bool:
        """Install AWS CLI for S3 bucket access"""
        awscli_config = config.get('config', {})
        version = awscli_config.get('version', '2')
        
        if version == '2':
            script = '''
set -e
echo "Installing AWS CLI v2..."

# Download and install AWS CLI v2
cd /tmp
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt-get install -y unzip
unzip -q awscliv2.zip
sudo ./aws/install --update
rm -rf aws awscliv2.zip

# Verify installation
aws --version

echo "✅ AWS CLI v2 installation completed"
'''
        else:
            # AWS CLI v1 (legacy)
            script = '''
set -e
echo "Installing AWS CLI v1..."

# Install AWS CLI v1 via apt
sudo apt-get install -y awscli

# Verify installation
aws --version

echo "✅ AWS CLI v1 installation completed"
'''
        
        success, output = self.client.run_command(script, timeout=300)
        return success
    
    def _configure_firewall(self, config: Dict[str, Any]) -> bool:
        """Configure firewall settings (OS-agnostic)"""
        firewall_config = config.get('config', {})
        allowed_ports = firewall_config.get('allowed_ports', ['22', '80', '443'])
        
        # Ensure SSH port 22 is always in the allowed list to prevent lockout
        if '22' not in allowed_ports and 22 not in allowed_ports:
            allowed_ports.insert(0, '22')
        
        # Get OS-specific firewall packages
        firewall_packages = self.os_packages.get('firewall', {}).get('packages', ['ufw'])
        firewall_service = self.os_packages.get('firewall', {}).get('service', 'ufw')
        
        if self.os_info['package_manager'] == 'apt':
            # Ubuntu/Debian uses UFW
            script = f'''
set -e
echo "Configuring UFW firewall on Ubuntu/Debian..."

# Check if UFW is already installed
if ! command -v ufw &> /dev/null; then
    echo "Installing UFW..."
    {self.pkg_commands['install']} {' '.join(firewall_packages)}
else
    echo "UFW already installed"
fi

# Disable UFW first to prevent lockout during configuration
sudo ufw --force disable

# Reset UFW to defaults
sudo ufw --force reset

# Set default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# CRITICAL: Allow SSH first to prevent lockout
sudo ufw allow 22/tcp

# Allow other specified ports
'''
            for port in allowed_ports:
                if str(port) != '22':  # Skip 22 since we already added it
                    script += f'sudo ufw allow {port}\n'
            
            script += '''
# Enable UFW
sudo ufw --force enable

# Verify SSH is allowed
sudo ufw status | grep 22 || echo "⚠️  Warning: SSH port may not be properly configured"

echo "✅ UFW firewall configuration completed"
'''
        else:
            # RHEL/CentOS/Amazon Linux uses firewalld
            script = f'''
set -e
echo "Configuring firewalld on RHEL/CentOS/Amazon Linux..."

# Install firewalld if not present
if ! command -v firewall-cmd &> /dev/null; then
    echo "Installing firewalld..."
    {self.pkg_commands['install']} firewalld
fi

# Enable and start firewalld
{self.svc_commands['enable']} firewalld
{self.svc_commands['start']} firewalld

# Allow specified ports
'''
            for port in allowed_ports:
                script += f'sudo firewall-cmd --permanent --add-port={port}/tcp\n'
            
            script += '''
# Reload firewall rules
sudo firewall-cmd --reload

# Verify SSH is allowed
sudo firewall-cmd --list-ports | grep 22 || echo "⚠️  Warning: SSH port may not be properly configured"

echo "✅ firewalld configuration completed"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        return success
    
    def _install_ssl_certificates(self, config: Dict[str, Any]) -> bool:
        """Install SSL certificates"""
        ssl_config = config.get('config', {})
        provider = ssl_config.get('provider', 'letsencrypt')
        
        if provider == 'letsencrypt':
            script = '''
set -e
echo "Installing Certbot for Let's Encrypt..."

# Install Certbot
# sudo apt-get update  # Removed: apt-get update now runs once at start
sudo apt-get install -y certbot python3-certbot-apache

echo "✅ Certbot installation completed"
echo "ℹ️  Run 'sudo certbot --apache' to obtain SSL certificates"
'''
        else:
            print(f"⚠️  SSL provider '{provider}' not implemented")
            return True  # Don't fail deployment for this
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _install_monitoring_tools(self, config: Dict[str, Any]) -> bool:
        """Install monitoring tools"""
        monitoring_config = config.get('config', {})
        tools = monitoring_config.get('tools', ['htop'])
        
        script = f'''
set -e
echo "Installing monitoring tools..."

# Install monitoring tools
# sudo apt-get update  # Removed: apt-get update now runs once at start
sudo apt-get install -y {' '.join(tools)}

echo "✅ Monitoring tools installation completed"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def configure_services(self) -> bool:
        """Configure installed services"""
        print("🔧 Configuring installed services...")
        
        success = True
        
        # Configure web server document root and permissions
        if 'apache' in self.installed_dependencies or 'nginx' in self.installed_dependencies:
            success &= self._configure_web_server()
        
        # Configure database connections
        if 'mysql' in self.installed_dependencies:
            success &= self._configure_mysql_app_access()
        
        if 'postgresql' in self.installed_dependencies:
            success &= self._configure_postgresql_app_access()
        
        return success
    
    def _configure_web_server(self) -> bool:
        """Configure web server for application (OS-agnostic)"""
        web_user = self.user_info['web_user']
        web_group = self.user_info['web_group']
        
        # Get OS-specific configuration
        if self.os_info['package_manager'] == 'apt':
            # Ubuntu/Debian
            apache_service = 'apache2'
            apache_conf_dir = '/etc/apache2'
            apache_log_dir = '/var/log/apache2'
        else:
            # Amazon Linux/RHEL/CentOS
            apache_service = 'httpd'
            apache_conf_dir = '/etc/httpd'
            apache_log_dir = '/var/log/httpd'
        
        script = f'''
set -e
echo "Configuring web server on {self.os_type}..."

# Set proper permissions for web directory
sudo chown -R {web_user}:{web_group} /var/www/html
sudo chmod -R 755 /var/www/html

# Remove default index files that might conflict
sudo rm -f /var/www/html/index.html
sudo rm -f /var/www/html/index.nginx-debian.html

# Create a proper index.html for testing
cat > /tmp/index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Application Deployed Successfully</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.1);
            padding: 40px;
            border-radius: 15px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }}
        .success {{
            color: #4ade80;
            font-size: 2.5em;
            margin-bottom: 20px;
            text-align: center;
        }}
        .info {{
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }}
        .info h3 {{
            margin-top: 0;
            color: #fbbf24;
        }}
        .status-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .status-item {{
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .status-item strong {{
            display: block;
            color: #fbbf24;
            margin-bottom: 5px;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            opacity: 0.8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success">✅ Deployment Successful!</div>
        
        <div class="info">
            <h3>🚀 Your Application is Live</h3>
            <p>The web server has been successfully configured and is now serving your application.</p>
        </div>
        
        <div class="status-grid">
            <div class="status-item">
                <strong>Server</strong>
                Apache on {self.os_type.replace('_', ' ').title()}
            </div>
            <div class="status-item">
                <strong>Document Root</strong>
                /var/www/html
            </div>
            <div class="status-item">
                <strong>Web User</strong>
                {web_user}:{web_group}
            </div>
            <div class="status-item">
                <strong>Status</strong>
                🟢 Online
            </div>
        </div>
        
        <div class="info">
            <h3>📁 Next Steps</h3>
            <p>You can now upload your application files to <code>/var/www/html</code> to replace this default page.</p>
            <p>The web server is configured with proper permissions and security settings.</p>
        </div>
        
        <div class="footer">
            <p>Deployed via GitHub Actions • Amazon Lightsail</p>
        </div>
    </div>
</body>
</html>
EOF

sudo mv /tmp/index.html /var/www/html/index.html
sudo chown {web_user}:{web_group} /var/www/html/index.html
sudo chmod 644 /var/www/html/index.html

# Configure Apache virtual host for better compatibility
if [ -d "{apache_conf_dir}" ]; then
    echo "Configuring Apache virtual host..."
    
    cat > /tmp/app.conf << 'EOF'
<VirtualHost *:80>
    DocumentRoot /var/www/html
    
    <Directory /var/www/html>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
    
    # Enable rewrite engine
    RewriteEngine On
    
    # Security headers
    Header always set X-Content-Type-Options nosniff
    Header always set X-Frame-Options DENY
    Header always set X-XSS-Protection "1; mode=block"
    
    ErrorLog {apache_log_dir}/app_error.log
    CustomLog {apache_log_dir}/app_access.log combined
</VirtualHost>
EOF

    if [ "{self.os_info['package_manager']}" = "apt" ]; then
        # Ubuntu/Debian
        sudo mv /tmp/app.conf {apache_conf_dir}/sites-available/app.conf
        sudo a2ensite app.conf
        sudo a2dissite 000-default.conf || true
        sudo a2enmod rewrite || true
        sudo a2enmod headers || true
        sudo systemctl reload {apache_service}
    else
        # Amazon Linux/RHEL/CentOS
        sudo mv /tmp/app.conf {apache_conf_dir}/conf.d/app.conf
        sudo systemctl restart {apache_service}
    fi
    
    echo "✅ Apache virtual host configured"
fi

echo "✅ Web server configuration completed on {self.os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        return success
    
    def _configure_mysql_app_access(self) -> bool:
        """Configure MySQL for application access"""
        # Skip configuration if using external RDS database
        mysql_config = self.config.get('dependencies', {}).get('mysql', {})
        if mysql_config.get('external', False):
            print("ℹ️  Skipping local MySQL configuration (using external RDS)")
            return True
        
        script = '''
set -e
echo "Configuring MySQL for application access..."

# Create application user (optional, basic setup)
# This is a basic setup - production should use more secure credentials
mysql -u root -proot123 -e "CREATE USER IF NOT EXISTS 'app'@'localhost' IDENTIFIED BY 'app123';" || true
mysql -u root -proot123 -e "GRANT ALL PRIVILEGES ON app_db.* TO 'app'@'localhost';" || true
mysql -u root -proot123 -e "FLUSH PRIVILEGES;" || true

echo "✅ MySQL application access configured"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        return success
    
    def _configure_postgresql_app_access(self) -> bool:
        """Configure PostgreSQL for application access"""
        # Skip configuration if using external RDS database
        pg_config = self.config.get('dependencies', {}).get('postgresql', {})
        if pg_config.get('external', False):
            print("ℹ️  Skipping local PostgreSQL configuration (using external RDS)")
            return True
        
        script = '''
set -e
echo "Configuring PostgreSQL for application access..."

# Create application user (basic setup)
sudo -u postgres createuser -D -A -P app || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE app_db TO app;" || true

echo "✅ PostgreSQL application access configured"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        return success
    
    def restart_services(self) -> bool:
        """Restart all installed services (OS-agnostic)"""
        print(f"🔄 Restarting installed services on {self.os_type}...")
        
        # Get OS-specific service names
        service_map = {
            'apache': self.os_packages.get('apache', {}).get('service', 'apache2'),
            'nginx': self.os_packages.get('nginx', {}).get('service', 'nginx'),
            'mysql': self.os_packages.get('mysql_server', {}).get('service', 'mysql'),
            'postgresql': self.os_packages.get('postgresql_server', {}).get('service', 'postgresql'),
            'redis': self.os_packages.get('redis', {}).get('service', 'redis-server'),
            'memcached': 'memcached',
            'docker': 'docker',
            'nodejs': 'nodejs-app'
        }
        
        success = True
        
        for dep in self.installed_dependencies:
            if dep in service_map:
                service_name = service_map[dep]
                restart_script = f'''
set -e
echo "Restarting {service_name} on {self.os_type}..."

# Check if service exists first
if {self.svc_commands['status']} {service_name} >/dev/null 2>&1 || systemctl list-unit-files | grep -q "^{service_name}.service"; then
    {self.svc_commands['restart']} {service_name}
    {self.svc_commands['enable']} {service_name}
    
    # Wait a moment and verify it's running
    sleep 2
    if {self.svc_commands['is_active']} {service_name}; then
        echo "✅ {service_name} restarted and running"
    else
        echo "⚠️  {service_name} restarted but not active"
        {self.svc_commands['status']} {service_name} --no-pager || true
    fi
else
    echo "ℹ️  {service_name} service not found, skipping"
fi
'''
                
                svc_success, output = self.client.run_command(restart_script, timeout=60)
                if not svc_success:
                    print(f"⚠️  Failed to restart {service_name}")
                    print(f"Output: {output}")
                    success = False
        
        return success

    def _install_external_database(self, db_type: str, config: Dict[str, Any]) -> bool:
        """
        Install external RDS database client and configure connection
        
        Args:
            db_type: Database type ('mysql' or 'postgresql')
            config: Database configuration from deployment config
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"🔗 Configuring external {db_type.upper()} RDS database...")
            
            # Get RDS configuration
            rds_config = config.get('rds', {})
            db_name = rds_config.get('database_name')
            
            if not db_name:
                print(f"❌ RDS database name not specified in configuration")
                return False
            
            # Initialize RDS manager
            # Note: Uses the same AWS credentials that GitHub Actions configured
            # No need to pass separate credentials - boto3 will use the environment
            rds_manager = LightsailRDSManager(
                instance_name=self.client.instance_name,
                region=rds_config.get('region', 'us-east-1')
            )
            
            # Get RDS connection details
            print(f"📡 Retrieving RDS connection details for {db_name}...")
            connection_details = rds_manager.get_rds_connection_details(db_name)
            
            if not connection_details:
                print(f"❌ Failed to retrieve RDS connection details for {db_name}")
                return False
            
            # Install database client
            print(f"📦 Installing {db_type} client...")
            client_success = self._install_database_client(db_type)
            
            if not client_success:
                print(f"❌ Failed to install {db_type} client")
                return False
            
            # Test database connectivity
            print(f"🔍 Testing database connectivity...")
            connectivity_success = rds_manager.test_rds_connectivity(
                connection_details, 
                rds_config.get('master_database', 'app_db')
            )
            
            if not connectivity_success:
                print(f"⚠️  Database connectivity test failed, but continuing...")
            
            # Configure environment variables for application
            print(f"⚙️  Configuring environment variables...")
            env_vars = rds_manager.create_database_env_vars(
                connection_details, 
                rds_config.get('master_database', 'app_db')
            )
            env_success = self._create_environment_file(env_vars, config)
            
            if not env_success:
                print(f"⚠️  Failed to configure environment variables")
                return False
            
            print(f"✅ External {db_type.upper()} RDS database configured successfully")
            print(f"   Host: {connection_details['endpoint']}")
            print(f"   Port: {connection_details['port']}")
            print(f"   Database: {connection_details['database_name']}")
            print(f"   Username: {connection_details['master_username']}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error configuring external {db_type} database: {str(e)}")
            return False
    
    def _install_database_client(self, db_type: str) -> bool:
        """Install database client tools (OS-agnostic)"""
        if db_type == 'mysql':
            # Get OS-specific MySQL client packages
            mysql_client_packages = self.os_packages.get('mysql_client', {}).get('packages', ['mysql-client'])
            
            script = f'''
set -e
echo "Installing MySQL client on {self.os_type}..."

# Install MySQL client
{self.pkg_commands['install']} {' '.join(mysql_client_packages)}

echo "✅ MySQL client installation completed on {self.os_type}"
'''
        elif db_type == 'postgresql':
            # Get OS-specific PostgreSQL client packages
            pg_client_packages = self.os_packages.get('postgresql_client', {}).get('packages', ['postgresql-client'])
            
            script = f'''
set -e
echo "Installing PostgreSQL client on {self.os_type}..."

# Install PostgreSQL client
{self.pkg_commands['install']} {' '.join(pg_client_packages)}

echo "✅ PostgreSQL client installation completed on {self.os_type}"
'''
        else:
            print(f"❌ Unsupported database type: {db_type}")
            return False
        
        success, output = self.client.run_command(script, timeout=420)
        return success
    
    def _create_environment_file(self, env_vars: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Create environment file with database configuration"""
        try:
            # Add any custom environment variables from config
            custom_env = config.get('rds', {}).get('environment', {})
            env_vars.update(custom_env)
            
            # Create environment file
            env_content = '\n'.join([f'{key}={value}' for key, value in env_vars.items()])
            
            # Get OS-specific user and group information
            web_user = self.user_info.get('web_user', 'www-data')
            web_group = self.user_info.get('web_group', 'www-data')
            
            script = f'''
set -e
echo "Configuring database environment variables..."

# Create environment file in /opt/app
sudo mkdir -p /opt/app
cat << 'EOF' | sudo tee /opt/app/database.env > /dev/null
{env_content}
EOF

# Set proper permissions for /opt/app/database.env (readable by web group)
sudo chmod 640 /opt/app/database.env
sudo chown root:{web_group} /opt/app/database.env

# Also create a copy in web directory for direct access
sudo cp /opt/app/database.env /var/www/html/.env
sudo chmod 640 /var/www/html/.env
sudo chown {web_user}:{web_group} /var/www/html/.env

echo "✅ Database environment configuration completed"
echo "Environment file created at: /opt/app/database.env"
echo "Environment file copied to: /var/www/html/.env"
'''
            
            success, output = self.client.run_command(script, timeout=60)
            
            if success:
                print("📝 Database environment variables configured:")
                for key, value in env_vars.items():
                    if 'PASSWORD' in key:
                        print(f"   {key}=***")
                    else:
                        print(f"   {key}={value}")
            
            return success
            
        except Exception as e:
            print(f"❌ Error creating environment file: {str(e)}")
            return False

    def _configure_database_environment(self, db_type: str, connection_details: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Configure environment variables for database connection"""
        try:
            # Create environment file for database configuration
            env_vars = {
                f'DB_TYPE': db_type.upper(),
                f'DB_HOST': connection_details['host'],
                f'DB_PORT': str(connection_details['port']),
                f'DB_NAME': connection_details['database'],
                f'DB_USERNAME': connection_details['username'],
                f'DB_PASSWORD': connection_details['password'],
                f'DB_EXTERNAL': 'true'
            }
            
            # Add any custom environment variables from config
            custom_env = config.get('environment', {})
            env_vars.update(custom_env)
            
            # Create environment file
            env_content = '\n'.join([f'{key}={value}' for key, value in env_vars.items()])
            
            # Get OS-specific user and group information
            web_user = self.user_info.get('web_user', 'www-data')
            web_group = self.user_info.get('web_group', 'www-data')
            
            script = f'''
set -e
echo "Configuring database environment variables..."

# Create environment file in /opt/app
sudo mkdir -p /opt/app
cat << 'EOF' | sudo tee /opt/app/database.env > /dev/null
{env_content}
EOF

# Set proper permissions for /opt/app/database.env (readable by web group)
sudo chmod 640 /opt/app/database.env
sudo chown root:{web_group} /opt/app/database.env

# Also create a copy in web directory for direct access
sudo cp /opt/app/database.env /var/www/html/.env
sudo chmod 640 /var/www/html/.env
sudo chown {web_user}:{web_group} /var/www/html/.env

echo "✅ Database environment configuration completed"
echo "Environment file created at: /opt/app/database.env"
echo "Environment file copied to: /var/www/html/.env"
'''
            
            success, output = self.client.run_command(script, timeout=60)
            
            if success:
                print("📝 Database environment variables configured:")
                for key, value in env_vars.items():
                    if 'PASSWORD' in key:
                        print(f"   {key}=***")
                    else:
                        print(f"   {key}={value}")
            
            return success
            
        except Exception as e:
            print(f"❌ Error configuring database environment: {str(e)}")
            return False

    def get_installation_summary(self) -> Dict[str, Any]:
        """Get summary of dependency installation"""
        return {
            'installed': self.installed_dependencies,
            'failed': self.failed_dependencies,
            'total_enabled': len(self.get_enabled_dependencies()),
            'success_rate': len(self.installed_dependencies) / max(1, len(self.get_enabled_dependencies())) * 100
        }
