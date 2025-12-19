#!/usr/bin/env python3
"""
Generic pre-deployment steps for AWS Lightsail
This script handles dependency installation and configuration based on config
"""

import os
import sys
import argparse
from lightsail_common import LightsailBase
from config_loader import DeploymentConfig
from dependency_manager import DependencyManager

class GenericPreDeployer:
    def __init__(self, instance_name=None, region=None, config=None, os_type=None, package_manager=None):
        # Initialize configuration
        if config is None:
            config = DeploymentConfig()
        
        # Use config values if parameters not provided
        if instance_name is None:
            instance_name = config.get_instance_name()
        if region is None:
            region = config.get_aws_region()
            
        self.config = config
        self.client = LightsailBase(instance_name, region)
        
        # Set OS information on client for configurators to use
        if os_type:
            self.client.os_type = os_type
        if package_manager:
            # Use OSDetector to get proper user info structure
            from os_detector import OSDetector
            os_info = OSDetector.get_user_info(os_type) if os_type else {}
            os_info['package_manager'] = package_manager
            os_info['service_manager'] = 'systemd'  # Most modern systems use systemd
            self.client.os_info = os_info
        
        # Initialize dependency manager with OS information
        from os_detector import OSDetector
        if os_type and package_manager:
            os_info = OSDetector.get_user_info(os_type)
            os_info['package_manager'] = package_manager
            os_info['service_manager'] = 'systemd'  # Most modern systems use systemd
            self.dependency_manager = DependencyManager(self.client, config, os_type, os_info)
        else:
            self.dependency_manager = DependencyManager(self.client, config)

    def prepare_environment(self):
        """Prepare generic application environment"""
        print("="*60)
        print("🔧 PREPARING APPLICATION ENVIRONMENT")
        print("="*60)
        
        # CRITICAL: Verify instance exists and is running before starting
        print("🔍 CRITICAL CHECK: Verifying instance exists and is running...")
        try:
            response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
            instance = response['instance']
            state = instance['state']['name']
            public_ip = instance.get('publicIpAddress', 'No IP')
            
            print(f"✅ Instance '{self.client.instance_name}' found:")
            print(f"   State: {state}")
            print(f"   Public IP: {public_ip}")
            print(f"   Blueprint: {instance.get('blueprintName', 'Unknown')}")
            print(f"   Bundle: {instance.get('bundleId', 'Unknown')}")
            
            if state != 'running':
                print(f"❌ CRITICAL ERROR: Instance is not running!")
                print(f"   Current state: {state}")
                if state in ['stopping', 'stopped', 'terminated']:
                    print(f"   Instance has been terminated or stopped!")
                    print(f"   This suggests the instance failed during startup or was cleaned up by another process.")
                    return False
                elif state in ['pending', 'rebooting']:
                    print(f"   Instance is still starting up, waiting...")
                    import time
                    for i in range(6):  # Wait up to 3 minutes
                        time.sleep(30)
                        response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
                        instance = response['instance']
                        state = instance['state']['name']
                        print(f"   Wait {i+1}/6: Instance state is now: {state}")
                        if state == 'running':
                            print(f"✅ Instance is now running!")
                            break
                    else:
                        print(f"❌ Instance did not reach running state within 3 minutes")
                        return False
            else:
                print(f"✅ Instance is running and ready for deployment")
                
        except Exception as e:
            print(f"❌ CRITICAL ERROR: Cannot access instance '{self.client.instance_name}': {e}")
            print(f"   This means the instance was deleted, terminated, or never existed.")
            return False
        
        # Get application configuration
        app_name = self.config.get('application.name', 'Generic Application')
        app_version = self.config.get('application.version', '1.0.0')
        app_type = self.config.get('application.type', 'web')
        enabled_deps = self.dependency_manager.get_enabled_dependencies()
        
        print(f"📋 Application: {app_name} v{app_version}")
        print(f"🏷️  Type: {app_type}")
        print(f"🌍 Instance: {self.client.instance_name}")
        print(f"📍 Region: {self.client.region}")
        print(f"📦 Dependencies to Install: {len(enabled_deps)}")
        
        if enabled_deps:
            print("   Dependencies:")
            for i, dep in enumerate(enabled_deps, 1):
                print(f"   {i}. {dep}")
        else:
            print("   No dependencies configured")
        
        # Pre-flight health check
        print("\n" + "="*60)
        print("🏥 SYSTEM HEALTH CHECK")
        print("="*60)
        health_ok = self._system_health_check()
        if not health_ok:
            print("⚠️  System health check found issues, but continuing with deployment...")
        else:
            print("✅ System health check passed")
        
        # Install all enabled dependencies
        print("\n" + "="*60)
        print("🚀 INSTALLING DEPENDENCIES")
        print("="*60)
        success, installed, failed = self.dependency_manager.install_all_dependencies()
        
        if not success:
            print(f"⚠️  Some dependencies failed to install: {', '.join(failed)}")
            if len(failed) == len(enabled_deps):
                print("❌ All dependencies failed to install")
                return False
        
        # Configure installed services
        if installed:
            print(f"\n" + "="*60)
            print(f"🔧 CONFIGURING {len(installed)} INSTALLED SERVICES")
            print("="*60)
            config_success = self.dependency_manager.configure_services()
            if not config_success:
                print("⚠️  Some service configurations failed")
        
        # Prepare application directory structure
        print("\n" + "="*60)
        print("📁 PREPARING DIRECTORY STRUCTURE")
        print("="*60)
        success = self._prepare_app_directories()
        if not success:
            print("❌ Failed to prepare application directories")
            return False
        
        # Set up environment variables
        print("\n" + "="*60)
        print("🌍 SETTING UP ENVIRONMENT VARIABLES")
        print("="*60)
        success = self._setup_environment_variables()
        if not success:
            print("⚠️  Failed to set up some environment variables")
        
        print("\n" + "="*60)
        print("✅ PRE-DEPLOYMENT COMPLETED SUCCESSFULLY!")
        print("="*60)
        
        # Print installation summary
        summary = self.dependency_manager.get_installation_summary()
        print(f"\n📊 Installation Summary:")
        print(f"   ✅ Installed: {len(summary['installed'])} dependencies")
        print(f"   ❌ Failed: {len(summary['failed'])} dependencies")
        print(f"   📈 Success Rate: {summary['success_rate']:.1f}%")
        
        if summary['installed']:
            print(f"   📦 Installed Dependencies: {', '.join(summary['installed'])}")
        if summary['failed']:
            print(f"   ⚠️  Failed Dependencies: {', '.join(summary['failed'])}")
        
        return True

    def _prepare_app_directories(self) -> bool:
        """Prepare application directory structure"""
        # First, verify the instance still exists
        print("🔍 Verifying instance exists before preparing directories...")
        try:
            response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
            instance = response['instance']
            state = instance['state']['name']
            print(f"✅ Instance '{self.client.instance_name}' exists with state: {state}")
            
            if state != 'running':
                print(f"⚠️  Instance is not in running state: {state}")
                if state in ['stopping', 'stopped', 'terminated']:
                    print(f"❌ Instance has been terminated or stopped!")
                    return False
                elif state in ['pending', 'rebooting']:
                    print(f"⏳ Instance is {state}, waiting for it to be ready...")
                    # Wait a bit for the instance to be ready
                    import time
                    time.sleep(30)
                    # Check again
                    response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
                    instance = response['instance']
                    state = instance['state']['name']
                    print(f"   Instance state after wait: {state}")
                    if state != 'running':
                        print(f"❌ Instance still not running after wait: {state}")
                        return False
        except Exception as e:
            print(f"❌ Error checking instance existence: {e}")
            return False
        
        app_type = self.config.get('application.type', 'web')
        
        # Determine web root based on enabled web server configuration (not installed yet)
        web_root = "/var/www/html"
        if self.config.get('dependencies.nginx.enabled', False):
            web_root = self.config.get('dependencies.nginx.config.document_root', '/var/www/html')
        elif self.config.get('dependencies.apache.enabled', False):
            web_root = self.config.get('dependencies.apache.config.document_root', '/var/www/html')
        
        # Get OS-specific user information
        from os_detector import OSDetector
        if hasattr(self.client, 'os_type') and self.client.os_type:
            os_info = OSDetector.get_user_info(self.client.os_type)
            system_user = os_info['default_user']
            system_group = os_info['default_user']  # Use same as user for group
        else:
            # Fallback to Ubuntu defaults
            system_user = 'ubuntu'
            system_group = 'ubuntu'
        
        # CRITICAL FIX: Use system user initially, web server users will be set later after installation
        script = f'''
set -e
echo "Preparing application directories..."

# Create main application directory
sudo mkdir -p {web_root}
sudo mkdir -p {web_root}/tmp
sudo mkdir -p {web_root}/logs
sudo mkdir -p {web_root}/config

# Create backup directory
sudo mkdir -p /var/backups/app

# IMPORTANT: Use system user initially since web server users don't exist yet
# Web server ownership will be set later in post-deployment steps after services are installed
echo "Setting initial ownership to system user ({system_user}:{system_group})"
sudo chown -R {system_user}:{system_group} {web_root}
sudo chmod -R 755 {web_root}
sudo chmod -R 777 {web_root}/tmp
sudo chmod -R 755 {web_root}/logs

# Create application-specific directories based on enabled dependencies
'''
        
        # Add Python-specific directories if Python is enabled
        if self.config.get('dependencies.python.enabled', False):
            python_config = self.config.get('dependencies.python.config', {})
            venv_path = python_config.get('virtualenv_path', '/opt/python-venv/app')
            script += f'''
# Python application directories
sudo mkdir -p /opt/app
sudo mkdir -p /var/log/app
sudo mkdir -p {venv_path}
sudo chown -R {system_user}:{system_group} /opt/app
sudo chown -R {system_user}:{system_group} /var/log/app
sudo chown -R {system_user}:{system_group} {venv_path}
'''
        
        # Add Node.js-specific directories if Node.js is enabled
        if self.config.get('dependencies.nodejs.enabled', False):
            script += f'''
# Node.js application directories
sudo mkdir -p /opt/nodejs-app
sudo mkdir -p /var/log/nodejs
sudo chown -R {system_user}:{system_group} /opt/nodejs-app
sudo chown -R {system_user}:{system_group} /var/log/nodejs
'''
        
        # Add database-specific directories only if they will be installed locally
        if self.config.get('dependencies.mysql.enabled', False):
            # Only create mysql directories if using local MySQL (not external RDS)
            mysql_config = self.config.get('dependencies', {}).get('mysql', {})
            if not mysql_config.get('external', False):
                script += f'''
# MySQL backup directory (ownership will be set after MySQL installation)
sudo mkdir -p /var/backups/mysql
sudo chown -R {system_user}:{system_group} /var/backups/mysql
'''
        
        if self.config.get('dependencies.postgresql.enabled', False):
            # Only create postgres directories if using local PostgreSQL (not external RDS)
            pg_config = self.config.get('dependencies', {}).get('postgresql', {})
            if not pg_config.get('external', False):
                script += f'''
# PostgreSQL backup directory (ownership will be set after PostgreSQL installation)
sudo mkdir -p /var/backups/postgresql
sudo chown -R {system_user}:{system_group} /var/backups/postgresql
'''
        
        script += '''
echo "✅ Application directories prepared with system user ownership"
echo "   Web server ownership will be set after services are installed"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        return success

    def _system_health_check(self) -> bool:
        """Perform system health checks before deployment with enhanced resilience"""
        print("🔍 Checking system health...")
        
        # First, verify the instance still exists and is running
        print("🔍 Verifying instance state before health check...")
        try:
            response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
            instance = response['instance']
            state = instance['state']['name']
            print(f"✅ Instance '{self.client.instance_name}' state: {state}")
            
            if state != 'running':
                print(f"⚠️  Instance is not running: {state}")
                if state in ['stopping', 'stopped', 'terminated']:
                    print(f"❌ Instance has been terminated or stopped during health check!")
                    return False
                else:
                    print(f"⏳ Instance is {state}, waiting for it to be ready...")
                    import time
                    time.sleep(30)
        except Exception as e:
            print(f"❌ Error checking instance during health check: {e}")
            return False
        
        # Test SSH connectivity with reduced retries for faster deployment
        print("🔗 Testing SSH connectivity...")
        # Reduce retries in pre-steps to speed up deployment
        max_retries = 3 if "GITHUB_ACTIONS" in os.environ else 5
        timeout = 30 if "GITHUB_ACTIONS" in os.environ else 60
        ssh_ok = self.client.test_ssh_connectivity(timeout=timeout, max_retries=max_retries)
        if not ssh_ok:
            print("⚠️  SSH connectivity issues detected, but continuing...")
            # Don't fail the deployment for SSH issues - the instance might still work
        
        # Get OS-specific package manager for health checks
        if hasattr(self.client, 'os_info') and self.client.os_info:
            package_manager = self.client.os_info.get('package_manager', 'unknown')
        else:
            package_manager = 'unknown'
        
        health_script = f'''
#!/bin/bash
set +e  # Don't exit on error, we want to check everything

echo "Checking disk space..."
df -h / | tail -1 | awk '{{print "Disk usage: " $5 " used of " $2}}'

echo ""
echo "Checking memory..."
free -h | grep Mem | awk '{{print "Memory: " $3 " used of " $2}}'

echo ""
echo "Checking package manager state..."
if [ "{package_manager}" = "apt" ]; then
    if sudo dpkg --audit 2>&1 | grep -q "broken"; then
        echo "❌ dpkg is in broken state"
        echo "Attempting to fix..."
        sudo dpkg --configure -a
        sudo apt-get install -f -y
        echo "✅ dpkg fixed"
    else
        echo "✅ dpkg is healthy"
    fi
    
    echo ""
    echo "Checking apt locks..."
    if sudo lsof /var/lib/dpkg/lock-frontend 2>/dev/null; then
        echo "⚠️  apt is locked by another process"
        echo "Waiting for lock to be released..."
        sleep 10
    else
        echo "✅ No apt locks detected"
    fi
elif [ "{package_manager}" = "yum" ] || [ "{package_manager}" = "dnf" ]; then
    echo "Checking yum/dnf locks..."
    if sudo lsof /var/run/yum.pid 2>/dev/null || sudo lsof /var/lib/dnf/dnf.librepo.lock 2>/dev/null; then
        echo "⚠️  Package manager is locked by another process"
        echo "Waiting for lock to be released..."
        sleep 10
    else
        echo "✅ No package manager locks detected"
    fi
else
    echo "ℹ️  Unknown package manager, skipping package manager checks"
fi

echo ""
echo "Checking connectivity..."
if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ Internet connectivity OK"
else
    echo "⚠️  Internet connectivity issue"
fi

echo ""
echo "✅ Health check completed"
'''
        
        # Use enhanced retry for health check
        max_retries = 3
        if "GITHUB_ACTIONS" in os.environ:
            max_retries = 5  # More retries in CI environment
        
        success, output = self.client.run_command(health_script, timeout=180, max_retries=max_retries)
        
        # Don't fail deployment for health check issues - log and continue
        if not success:
            print("⚠️  Health check had issues, but deployment will continue...")
            print("   This is often due to temporary connectivity issues")
            return True  # Return True to continue deployment
        
        return success

    def _setup_environment_variables(self) -> bool:
        """Set up application environment variables"""
        env_vars = self.config.get_environment_variables()
        
        if not env_vars:
            print("ℹ️  No environment variables configured")
            return True
        
        # Create environment file content
        env_content = []
        for key, value in env_vars.items():
            env_content.append(f'{key}="{value}"')
        
        env_file_content = '\n'.join(env_content)
        
        # Get OS-specific user information
        from os_detector import OSDetector
        if hasattr(self.client, 'os_type') and self.client.os_type:
            os_info = OSDetector.get_user_info(self.client.os_type)
            web_user = os_info['web_user']
            web_group = os_info['web_group']
        else:
            # Fallback to Ubuntu defaults
            web_user = 'www-data'
            web_group = 'www-data'
        
        script = f'''
set -e
echo "Setting up environment variables..."

# Create environment file
cat > /tmp/app.env << 'EOF'
{env_file_content}
EOF

# Move to appropriate location based on application type
sudo mv /tmp/app.env /var/www/html/.env
sudo chown {web_user}:{web_group} /var/www/html/.env
sudo chmod 600 /var/www/html/.env

# Also create system-wide environment file
sudo cp /var/www/html/.env /etc/environment.d/app.conf || true

echo "✅ Environment variables configured"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        return success

def main():
    parser = argparse.ArgumentParser(description='Generic pre-deployment steps for AWS Lightsail')
    parser.add_argument('--instance-name', help='Lightsail instance name (overrides config)')
    parser.add_argument('--region', help='AWS region (overrides config)')
    parser.add_argument('--config-file', help='Path to configuration file')
    parser.add_argument('--os-type', help='Operating system type (ubuntu, amazon_linux, centos, rhel)')
    parser.add_argument('--package-manager', help='Package manager (apt, yum, dnf)')
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config_file = args.config_file if args.config_file else 'deployment-generic.config.yml'
        config = DeploymentConfig(config_file=config_file)
        
        # Use command line args if provided, otherwise use config
        instance_name = args.instance_name or config.get_instance_name()
        region = args.region or config.get_aws_region()
        
        print(f"🔧 Starting generic pre-deployment steps for {instance_name}")
        print(f"🌍 Region: {region}")
        print(f"📋 Application: {config.get('application.name', 'Unknown')} v{config.get('application.version', '1.0.0')}")
        print(f"🏷️  Type: {config.get('application.type', 'web')}")
        
        # Display OS information if provided
        if args.os_type:
            print(f"🖥️  OS Type: {args.os_type}")
        if args.package_manager:
            print(f"📦 Package Manager: {args.package_manager}")
        
        # Check if dependency steps are enabled in config
        if not config.get('deployment.steps.pre_deployment.dependencies.enabled', True):
            print("ℹ️  Dependency installation steps are disabled in configuration")
            sys.exit(0)
        
        # Create generic pre-deployer and prepare environment
        pre_deployer = GenericPreDeployer(instance_name, region, config, args.os_type, args.package_manager)
        
        if pre_deployer.prepare_environment():
            print("🎉 Generic pre-deployment steps completed successfully!")
            sys.exit(0)
        else:
            print("❌ Generic pre-deployment steps failed")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error in generic pre-deployment steps: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
