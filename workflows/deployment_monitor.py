#!/usr/bin/env python3
"""
Deployment Monitor for AWS Lightsail
This script provides monitoring and health check capabilities for deployed applications
"""

import sys
import time
import argparse
from datetime import datetime
from lightsail_common import LightsailBase
from config_loader import DeploymentConfig

class DeploymentMonitor:
    """Monitor deployment health and status"""
    
    def __init__(self, instance_name=None, region=None, config=None):
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
    
    def check_system_health(self):
        """Check overall system health"""
        print("="*60)
        print("🏥 SYSTEM HEALTH CHECK")
        print("="*60)
        print(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Check instance status
        instance_info = self.client.get_instance_info()
        if instance_info:
            print(f"\n🖥️  Instance Status:")
            print(f"   Name: {instance_info['name']}")
            print(f"   State: {instance_info['state']}")
            print(f"   Public IP: {instance_info.get('public_ip', 'N/A')}")
            print(f"   Blueprint: {instance_info.get('blueprint', 'N/A')}")
        
        # Check services
        self._check_services()
        
        # Check disk usage
        self._check_disk_usage()
        
        # Check memory usage
        self._check_memory_usage()
        
        # Check application health
        self._check_application_health()
        
        print("\n" + "="*60)
        print("✅ HEALTH CHECK COMPLETED")
        print("="*60)
    
    def _check_services(self):
        """Check status of key services"""
        print(f"\n🔧 Service Status:")
        
        services_script = '''
echo "Checking service status..."

# Check web servers
if systemctl is-active --quiet apache2; then
    echo "✅ Apache: Running"
    systemctl status apache2 --no-pager -l | head -3
else
    echo "❌ Apache: Not running"
fi

if systemctl is-active --quiet nginx; then
    echo "✅ Nginx: Running"
else
    echo "ℹ️  Nginx: Not installed/running"
fi

# Check databases
if systemctl is-active --quiet mysql; then
    echo "✅ MySQL: Running"
    mysql -u root -proot123 -e "SELECT VERSION() as mysql_version;" 2>/dev/null || echo "⚠️  MySQL connection issue"
else
    echo "ℹ️  MySQL: Not running"
fi

if systemctl is-active --quiet postgresql; then
    echo "✅ PostgreSQL: Running"
else
    echo "ℹ️  PostgreSQL: Not running"
fi

# Check PHP-FPM
if systemctl is-active --quiet php8.1-fpm; then
    echo "✅ PHP-FPM: Running"
else
    echo "ℹ️  PHP-FPM: Not running"
fi
'''
        
        success, output = self.client.run_command(services_script, timeout=60)
        if success:
            for line in output.split('\n'):
                if line.strip():
                    print(f"   {line}")
    
    def _check_disk_usage(self):
        """Check disk usage"""
        print(f"\n💾 Disk Usage:")
        
        disk_script = '''
echo "Checking disk usage..."
df -h / | tail -1 | awk '{print "Root: " $3 "/" $2 " (" $5 " used)"}'
df -h /var/www/html 2>/dev/null | tail -1 | awk '{print "Web Root: " $3 "/" $2 " (" $5 " used)")' || echo "Web Root: Same as root partition"

# Check log sizes
echo "Log file sizes:"
du -sh /var/log/apache2/* 2>/dev/null | head -5 || echo "No Apache logs found"
du -sh /var/log/mysql/* 2>/dev/null | head -3 || echo "No MySQL logs found"
'''
        
        success, output = self.client.run_command(disk_script, timeout=30)
        if success:
            for line in output.split('\n'):
                if line.strip() and not line.startswith('Checking'):
                    print(f"   {line}")
    
    def _check_memory_usage(self):
        """Check memory usage"""
        print(f"\n🧠 Memory Usage:")
        
        memory_script = '''
echo "Checking memory usage..."
free -h | grep -E "Mem:|Swap:" | awk '{print $1 " " $3 "/" $2 " (" int($3/$2*100) "% used)"}'

# Check top processes by memory
echo "Top memory consumers:"
ps aux --sort=-%mem | head -6 | tail -5 | awk '{print $11 ": " $4 "% (" $6 " KB)"}'
'''
        
        success, output = self.client.run_command(memory_script, timeout=30)
        if success:
            for line in output.split('\n'):
                if line.strip() and not line.startswith('Checking'):
                    print(f"   {line}")
    
    def _check_application_health(self):
        """Check application-specific health"""
        print(f"\n🌐 Application Health:")
        
        health_config = self.config.get_health_check_config()
        endpoint = health_config.get('endpoint', '/')
        expected_content = health_config.get('expected_content', 'Hello')
        
        app_script = f'''
echo "Checking application health..."

# Test local HTTP response
if curl -s --connect-timeout 10 http://localhost{endpoint} > /tmp/health_check.html; then
    if grep -q "{expected_content}" /tmp/health_check.html; then
        echo "✅ Application: Responding correctly"
        echo "   Response contains expected content: '{expected_content}'"
    else
        echo "⚠️  Application: Responding but content unexpected"
        echo "   First 100 chars: $(head -c 100 /tmp/health_check.html)"
    fi
else
    echo "❌ Application: Not responding to HTTP requests"
fi

# Check application files
if [ -f "/var/www/html/index.php" ]; then
    echo "✅ Main application file exists"
elif [ -f "/var/www/html/index.html" ]; then
    echo "✅ Main HTML file exists"
else
    echo "⚠️  No main application file found"
fi

# Check environment file
if [ -f "/var/www/html/.env" ]; then
    echo "✅ Environment file exists"
    echo "   Variables: $(grep -c "=" /var/www/html/.env) configured"
else
    echo "⚠️  No environment file found"
fi

# Check database connectivity
if command -v mysql >/dev/null 2>&1; then
    if mysql -u root -proot123 -e "SELECT 1;" >/dev/null 2>&1; then
        echo "✅ Database: MySQL connection successful"
        echo "   Databases: $(mysql -u root -proot123 -e "SHOW DATABASES;" 2>/dev/null | wc -l) found"
    else
        echo "❌ Database: MySQL connection failed"
    fi
fi

rm -f /tmp/health_check.html
'''
        
        success, output = self.client.run_command(app_script, timeout=60)
        if success:
            for line in output.split('\n'):
                if line.strip() and not line.startswith('Checking'):
                    print(f"   {line}")
    
    def monitor_logs(self, lines=50, follow=False):
        """Monitor application logs"""
        print("="*60)
        print("📋 LOG MONITORING")
        print("="*60)
        
        if follow:
            print("🔄 Following logs (Press Ctrl+C to stop)...")
        else:
            print(f"📖 Showing last {lines} lines...")
        
        log_script = f'''
echo "=== Apache Error Log ==="
if [ -f "/var/log/apache2/error.log" ]; then
    tail -n {lines} /var/log/apache2/error.log
else
    echo "No Apache error log found"
fi

echo ""
echo "=== Apache Access Log ==="
if [ -f "/var/log/apache2/access.log" ]; then
    tail -n {lines} /var/log/apache2/access.log
else
    echo "No Apache access log found"
fi

echo ""
echo "=== MySQL Error Log ==="
if [ -f "/var/log/mysql/error.log" ]; then
    tail -n {lines} /var/log/mysql/error.log
else
    echo "No MySQL error log found"
fi
'''
        
        success, output = self.client.run_command(log_script, timeout=60)
        if success:
            print(output)
    
    def view_command_log(self, lines=50):
        """View command execution log"""
        print("="*60)
        print("📋 COMMAND EXECUTION LOG")
        print("="*60)
        
        success, log_content = self.client.get_command_log(lines)
        
        if success:
            if log_content.strip() and "No commands logged yet" not in log_content:
                print(f"📋 Last {lines} Commands Executed on Instance:")
                print("─" * 60)
                
                # Parse and display log entries
                log_lines = log_content.strip().split('\n')
                for i, line in enumerate(log_lines, 1):
                    if line.strip():
                        # Format: [timestamp] COMMAND: actual_command
                        if '] COMMAND: ' in line:
                            timestamp_part, command_part = line.split('] COMMAND: ', 1)
                            timestamp = timestamp_part.replace('[', '')
                            command = command_part.replace(' | ', '\n        ')  # Restore newlines
                            
                            print(f"{i:3d}. [{timestamp}]")
                            print(f"     {command}")
                        else:
                            print(f"{i:3d}. {line}")
                
                print("─" * 60)
                print(f"📊 Total commands: {len([l for l in log_lines if l.strip()])}")
                print(f"📁 Log location: /var/log/deployment-commands.log")
            else:
                print("📋 No commands found in execution log")
        else:
            print(f"❌ Failed to retrieve command log: {log_content}")
    
    def clear_command_log(self):
        """Clear command execution log"""
        print("="*60)
        print("🧹 CLEARING COMMAND LOG")
        print("="*60)
        
        success, message = self.client.clear_command_log()
        if success:
            print(f"✅ {message}")
        else:
            print(f"❌ Failed to clear log: {message}")
    
    def restart_services(self, services=None):
        """Restart specified services or all detected services"""
        if services is None:
            services = ['apache2', 'mysql', 'php8.1-fpm']
        
        print("="*60)
        print("🔄 RESTARTING SERVICES")
        print("="*60)
        
        for service in services:
            print(f"\n🔄 Restarting {service}...")
            
            restart_script = f'''
if systemctl is-enabled {service} >/dev/null 2>&1; then
    echo "Restarting {service}..."
    sudo systemctl restart {service}
    if systemctl is-active --quiet {service}; then
        echo "✅ {service} restarted successfully"
    else
        echo "❌ {service} failed to start"
        systemctl status {service} --no-pager -l | head -5
    fi
else
    echo "ℹ️  {service} is not installed or enabled"
fi
'''
            
            success, output = self.client.run_command(restart_script, timeout=60)
            if success:
                for line in output.split('\n'):
                    if line.strip():
                        print(f"   {line}")

def main():
    parser = argparse.ArgumentParser(description='Monitor AWS Lightsail deployment')
    parser.add_argument('--instance-name', help='Lightsail instance name')
    parser.add_argument('--region', help='AWS region')
    parser.add_argument('--config-file', help='Path to configuration file')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Health check command
    health_parser = subparsers.add_parser('health', help='Check system health')
    
    # Log monitoring command
    logs_parser = subparsers.add_parser('logs', help='Monitor logs')
    logs_parser.add_argument('--lines', type=int, default=50, help='Number of log lines to show')
    logs_parser.add_argument('--follow', action='store_true', help='Follow logs in real-time')
    
    # Service restart command
    restart_parser = subparsers.add_parser('restart', help='Restart services')
    restart_parser.add_argument('services', nargs='*', help='Services to restart (default: all)')
    
    # Command log viewing
    cmdlog_parser = subparsers.add_parser('cmdlog', help='View command execution log')
    cmdlog_parser.add_argument('--lines', type=int, default=50, help='Number of command log lines to show')
    cmdlog_parser.add_argument('--clear', action='store_true', help='Clear the command log')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        # Load configuration
        config_file = args.config_file if args.config_file else 'deployment-generic.config.yml'
        config = DeploymentConfig(config_file=config_file)
        
        # Create monitor
        monitor = DeploymentMonitor(args.instance_name, args.region, config)
        
        if args.command == 'health':
            monitor.check_system_health()
        elif args.command == 'logs':
            monitor.monitor_logs(args.lines, args.follow)
        elif args.command == 'restart':
            monitor.restart_services(args.services if args.services else None)
        elif args.command == 'cmdlog':
            if args.clear:
                monitor.clear_command_log()
            else:
                monitor.view_command_log(args.lines)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()