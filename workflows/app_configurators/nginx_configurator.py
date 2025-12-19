"""Nginx web server configurator"""

from .base_configurator import BaseConfigurator
from os_detector import OSDetector


class NginxConfigurator(BaseConfigurator):
    """Configure Nginx for the application"""
    
    def configure(self) -> bool:
        """Configure Nginx for the application"""
        # Get OS information from client
        os_type = getattr(self.client, 'os_type', 'ubuntu')
        os_info = getattr(self.client, 'os_info', {'package_manager': 'apt', 'user': 'ubuntu'})
        
        # Get OS-specific information
        self.user_info = OSDetector.get_user_info(os_type)
        self.pkg_commands = OSDetector.get_package_manager_commands(os_info['package_manager'])
        self.svc_commands = OSDetector.get_service_commands(os_info.get('service_manager', 'systemd'))
        
        document_root = self.config.get('dependencies.nginx.config.document_root', '/var/www/html')
        
        # CRITICAL: Fix directory ownership now that Nginx is installed
        print("🔧 Setting proper directory ownership for Nginx...")
        ownership_success = self._fix_directory_ownership(document_root)
        if not ownership_success:
            print("⚠️  Failed to set directory ownership, but continuing...")
        
        # Check if Node.js is enabled - if so, configure as reverse proxy
        nodejs_enabled = self.config.get('dependencies.nodejs.enabled', False)
        python_enabled = self.config.get('dependencies.python.enabled', False)
        
        if nodejs_enabled:
            return self._configure_nodejs_proxy()
        elif python_enabled:
            return self._configure_python_proxy()
        else:
            return self._configure_static_or_php(document_root)
    
    def _configure_nodejs_proxy(self) -> bool:
        """Configure Nginx as reverse proxy for Node.js"""
        print("🔧 Configuring Nginx as reverse proxy for Node.js...")
        
        script = '''
set -e
echo "Configuring Nginx as reverse proxy for Node.js application..."

# Create server block configuration for Node.js proxy
cat > /tmp/app << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}
EOF

# Install the configuration
sudo mv /tmp/app /etc/nginx/sites-available/app
sudo ln -sf /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app
sudo rm -f /etc/nginx/sites-enabled/default

echo "✅ Nginx configured as reverse proxy for Node.js"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        print(output)
        return success
    
    def _configure_python_proxy(self) -> bool:
        """Configure Nginx as reverse proxy for Python"""
        print("🔧 Configuring Nginx as reverse proxy for Python...")
        
        script = '''
set -e
echo "Configuring Nginx as reverse proxy for Python application..."

# Create server block configuration for Python proxy
cat > /tmp/app << 'EOF'
server {
    listen 80;
    server_name _;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Health check endpoint
    location /health {
        proxy_pass http://localhost:5000/health;
        access_log off;
    }
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}
EOF

# Install the configuration
sudo mv /tmp/app /etc/nginx/sites-available/app
sudo ln -sf /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app
sudo rm -f /etc/nginx/sites-enabled/default

echo "✅ Nginx configured as reverse proxy for Python"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        print(output)
        return success
    
    def _configure_static_or_php(self, document_root: str) -> bool:
        """Configure Nginx for static or PHP applications"""
        print("🔧 Configuring Nginx for static/PHP application...")
        
        script = f'''
set -e
echo "Configuring Nginx for application..."

# Check if this is a React/SPA application
if [ -f "{document_root}/index.html" ] && [ ! -f "{document_root}/index.php" ]; then
    echo "Detected React/SPA application"
    cat > /tmp/app << 'EOF'
server {{
    listen 80;
    server_name _;
    
    root {document_root};
    index index.html;
    
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    
    # Cache static assets
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {{
        expires 1y;
        add_header Cache-Control "public, immutable";
    }}
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}}
EOF
else
    echo "Detected PHP/traditional web application"
    cat > /tmp/app << 'EOF'
server {{
    listen 80;
    server_name _;
    
    root {document_root};
    index index.php index.html index.htm;
    
    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}
    
    location ~ \\\\.php$ {{
        include snippets/fastcgi-php.conf;
        # OS-agnostic PHP-FPM socket path
        fastcgi_pass unix:/var/run/php/php8.1-fpm.sock;
    }}
    
    location ~ /\\\\.ht {{
        deny all;
    }}
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}}
EOF
fi

# Install the configuration
sudo mv /tmp/app /etc/nginx/sites-available/app
sudo ln -sf /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app
sudo rm -f /etc/nginx/sites-enabled/default

echo "✅ Nginx configured for application"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        print(output)
        return success
    
    def _fix_directory_ownership(self, document_root: str) -> bool:
        """Fix directory ownership after Nginx installation"""
        print("🔧 Fixing directory ownership for web server...")
        
        # Get web server user/group from OS info
        nginx_user = self.user_info.get('nginx_user', 'nginx')
        nginx_group = self.user_info.get('nginx_group', 'nginx')
        
        script = f'''
set -e
echo "Fixing directory ownership for Nginx..."

# Check if nginx user exists
if id "{nginx_user}" &>/dev/null; then
    echo "✅ Nginx user '{nginx_user}' exists"
    
    # Set ownership for web directories
    echo "Setting ownership of {document_root} to {nginx_user}:{nginx_group}"
    sudo chown -R {nginx_user}:{nginx_group} {document_root}
    
    # Set proper permissions
    sudo chmod -R 755 {document_root}
    sudo chmod -R 777 {document_root}/tmp 2>/dev/null || true
    sudo chmod -R 755 {document_root}/logs 2>/dev/null || true
    
    echo "✅ Directory ownership fixed for Nginx"
else
    echo "⚠️  Nginx user '{nginx_user}' does not exist yet, keeping system user ownership"
    echo "   This is normal if Nginx hasn't been fully configured yet"
fi
'''
        
        success, output = self.client.run_command(script, timeout=60)
        print(output)
        return success