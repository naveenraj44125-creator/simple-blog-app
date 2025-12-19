"""Node.js application configurator"""
from .base_configurator import BaseConfigurator

class NodeJSConfigurator(BaseConfigurator):
    """Handles Node.js application configuration"""
    
    def configure(self) -> bool:
        """Configure Node.js application with systemd service (OS-agnostic)"""
        print("🔧 Configuring Node.js application...")
        
        # Get OS information from config if available
        os_type = getattr(self.config, 'os_type', 'ubuntu')
        os_info = getattr(self.config, 'os_info', {'user': 'ubuntu'})
        default_user = os_info.get('user', 'ubuntu')
        
        script = f'''
set -e
echo "Configuring Node.js for application on {os_type}..."

# Detect entry point file
ENTRY_POINT=""
if [ -f "/opt/nodejs-app/server.js" ]; then
    ENTRY_POINT="server.js"
    echo "✅ Found server.js as entry point"
elif [ -f "/opt/nodejs-app/app.js" ]; then
    ENTRY_POINT="app.js"
    echo "✅ Found app.js as entry point"
elif [ -f "/opt/nodejs-app/index.js" ]; then
    ENTRY_POINT="index.js"
    echo "✅ Found index.js as entry point"
else
    echo "❌ No entry point file found (server.js, app.js, or index.js)"
    ls -la /opt/nodejs-app/ || echo "Directory does not exist"
    exit 1
fi

# Install dependencies if package.json exists
if [ -f "/opt/nodejs-app/package.json" ]; then
    echo "📦 Installing Node.js dependencies..."
    cd /opt/nodejs-app && sudo -u {default_user} npm install --production 2>&1 | tee /tmp/npm-install.log
    echo "✅ Dependencies installed"
else
    echo "ℹ️  No package.json found, skipping dependency installation"
fi

# Create log directory
sudo mkdir -p /var/log/nodejs-app
sudo chown {default_user}:{default_user} /var/log/nodejs-app

# Create systemd service for Node.js app
echo "📝 Creating systemd service file with entry point: $ENTRY_POINT"
sudo tee /etc/systemd/system/nodejs-app.service > /dev/null << EOF
[Unit]
Description=Node.js Application
After=network.target

[Service]
Type=simple
User={default_user}
WorkingDirectory=/opt/nodejs-app
ExecStart=/usr/bin/node $ENTRY_POINT
Restart=always
RestartSec=10
Environment=NODE_ENV=production
Environment=PORT=3000
StandardOutput=append:/var/log/nodejs-app/output.log
StandardError=append:/var/log/nodejs-app/error.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable the service
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl enable nodejs-app.service

# Stop any existing instance
sudo systemctl stop nodejs-app.service 2>/dev/null || true

# Start the service
echo "🚀 Starting Node.js application service..."
sudo systemctl start nodejs-app.service

# Wait and check if service started successfully
sleep 5

if systemctl is-active --quiet nodejs-app.service; then
    echo "✅ Node.js app service started successfully"
    sudo systemctl status nodejs-app.service --no-pager
    
    # Check if app is listening on port 3000
    sleep 2
    if sudo ss -tlnp 2>/dev/null | grep -q ":3000" || sudo netstat -tlnp 2>/dev/null | grep -q ":3000"; then
        echo "✅ Application is listening on port 3000"
    else
        echo "⚠️  Application may not be listening on port 3000"
        sudo ss -tlnp 2>/dev/null | grep node || sudo netstat -tlnp 2>/dev/null | grep node || echo "No node process found listening"
    fi
    
    # Test local connection
    if curl -s http://localhost:3000/ > /dev/null; then
        echo "✅ Local connection to port 3000 successful"
    else
        echo "⚠️  Local connection to port 3000 failed"
    fi
else
    echo "❌ Node.js app service failed to start"
    sudo systemctl status nodejs-app.service --no-pager || true
    echo "=== Service Logs ==="
    sudo journalctl -u nodejs-app.service -n 50 --no-pager || true
    echo "=== Application Error Log ==="
    sudo cat /var/log/nodejs-app/error.log 2>/dev/null || echo "No error log found"
    exit 1
fi

echo "✅ Node.js application configured successfully on {os_type}"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        print(output)
        return success
