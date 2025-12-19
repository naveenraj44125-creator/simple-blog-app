"""Python application configurator"""

from .base_configurator import BaseConfigurator
from os_detector import OSDetector


class PythonConfigurator(BaseConfigurator):
    """Configure Python for the application"""
    
    def configure(self) -> bool:
        """Configure Python for the application"""
        # Get OS information from client
        os_type = getattr(self.client, 'os_type', 'ubuntu')
        os_info = getattr(self.client, 'os_info', {'package_manager': 'apt', 'user': 'ubuntu'})
        
        # Get OS-specific information
        self.user_info = OSDetector.get_user_info(os_type)
        self.pkg_commands = OSDetector.get_package_manager_commands(os_info['package_manager'])
        self.svc_commands = OSDetector.get_service_commands(os_info.get('service_manager', 'systemd'))
        
        app_type = self.config.get('application.type', 'web')
        
        if app_type == 'api':
            return self._configure_api_app()
        else:
            return self._configure_wsgi_app()
    
    def _configure_api_app(self) -> bool:
        """Configure Python API application with systemd service"""
        print("🔧 Configuring Python API application...")
        
        # Get the document root from nginx config or use default
        document_root = self.config.get('dependencies.nginx.config.document_root', '/opt/app')
        
        script = f'''
set -e
echo "Configuring Python for API application..."

# Check if app files exist
if [ ! -f "{document_root}/app.py" ]; then
    echo "❌ No app.py found in {document_root}"
    ls -la {document_root}/ || echo "Directory does not exist"
    exit 1
fi

# Install Python dependencies if requirements.txt exists
if [ -f "{document_root}/requirements.txt" ]; then
    echo "📦 Installing Python dependencies..."
    cd {document_root}
    
    # Ensure pip is installed
    if ! command -v pip3 &> /dev/null; then
        echo "Installing pip3..."
        {self.pkg_commands['update']}
        {self.pkg_commands['install']} python3-pip
    fi
    
    # Install dependencies
    sudo pip3 install -r requirements.txt 2>&1 | tee /tmp/pip-install.log
    echo "✅ Dependencies installed"
    
    # Ensure Gunicorn is installed (fallback)
    if ! command -v gunicorn &> /dev/null; then
        echo "📦 Installing Gunicorn as fallback..."
        sudo pip3 install gunicorn
    fi
else
    echo "ℹ️  No requirements.txt found, skipping dependency installation"
fi

# Create log directory
sudo mkdir -p /var/log/python-app
sudo chown {self.user_info['default_user']}:{self.user_info['default_user']} /var/log/python-app

# Create systemd service for Python app
echo "📝 Creating systemd service file..."
sudo tee /etc/systemd/system/python-app.service > /dev/null << EOF
[Unit]
Description=Python Flask Application
After=network.target

[Service]
Type=simple
User={self.user_info['default_user']}
WorkingDirectory={document_root}
Environment=PATH=/usr/bin:/usr/local/bin
Environment=FLASK_APP=app.py
Environment=FLASK_ENV=production
Environment=PORT=5000
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 60 app:app
Restart=always
RestartSec=10
StandardOutput=append:/var/log/python-app/output.log
StandardError=append:/var/log/python-app/error.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable the service
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl enable python-app.service

# Stop any existing instance
sudo systemctl stop python-app.service 2>/dev/null || true

# Start the service
echo "🚀 Starting Python application service..."
sudo systemctl start python-app.service

# Wait and check if service started successfully
sleep 5

if systemctl is-active --quiet python-app.service; then
    echo "✅ Python app service started successfully"
    sudo systemctl status python-app.service --no-pager
    
    # Check if app is listening on port 5000
    sleep 2
    if sudo ss -tlnp 2>/dev/null | grep -q ":5000" || sudo netstat -tlnp 2>/dev/null | grep -q ":5000"; then
        echo "✅ Application is listening on port 5000"
    else
        echo "⚠️  Application may not be listening on port 5000"
        sudo ss -tlnp 2>/dev/null | grep python || sudo netstat -tlnp 2>/dev/null | grep python || echo "No python process found listening"
    fi
    
    # Test local connection
    if curl -s http://localhost:5000/ > /dev/null; then
        echo "✅ Local connection to port 5000 successful"
    else
        echo "⚠️  Local connection to port 5000 failed"
    fi
else
    echo "❌ Python app service failed to start"
    sudo systemctl status python-app.service --no-pager || true
    echo "=== Service Logs ==="
    sudo journalctl -u python-app.service -n 50 --no-pager || true
    echo "=== Application Error Log ==="
    sudo cat /var/log/python-app/error.log 2>/dev/null || echo "No error log found"
    exit 1
fi

echo "✅ Python app service configured"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        print(output)
        return success
    
    def _configure_wsgi_app(self) -> bool:
        """Configure Python WSGI application with Apache"""
        print("🔧 Configuring Python WSGI application...")
        
        script = '''
set -e
echo "Configuring Python for web application..."

# Install mod_wsgi if Apache is present
apache_service=$(if [ "{self.user_info.get('web_user', 'www-data')}" = "www-data" ]; then echo "apache2"; else echo "httpd"; fi)
if {self.svc_commands['is_active']} $apache_service; then
    {self.pkg_commands['update']}
    if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then
        {self.pkg_commands['install']} libapache2-mod-wsgi-py3
        sudo a2enmod wsgi
    else
        {self.pkg_commands['install']} python3-mod_wsgi
    fi
    echo "✅ mod_wsgi configured for Apache"
fi
'''
        
        success, output = self.client.run_command(script, timeout=120)
        print(output)
        return success
