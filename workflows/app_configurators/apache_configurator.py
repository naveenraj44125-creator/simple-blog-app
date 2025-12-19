"""Apache web server configurator"""

from .base_configurator import BaseConfigurator


class ApacheConfigurator(BaseConfigurator):
    """Configure Apache for the application"""
    
    def configure(self) -> bool:
        """Configure Apache for the application"""
        app_type = self.config.get('application.type', 'web')
        document_root = self.config.get('dependencies.apache.config.document_root', '/var/www/html')
        
        print(f"🔧 Configuring Apache for {app_type} application...")
        
        # Get OS information from client
        if hasattr(self.client, 'os_info') and self.client.os_info:
            package_manager = self.client.os_info.get('package_manager', 'apt')
            web_user = self.client.os_info.get('web_user', 'www-data')
            web_group = self.client.os_info.get('web_group', 'www-data')
        else:
            # Fallback to Ubuntu defaults
            package_manager = 'apt'
            web_user = 'www-data'
            web_group = 'www-data'
        
        if package_manager == 'apt':
            # Ubuntu/Debian Apache configuration
            script = f'''
set -e
echo "Configuring Apache for application on Ubuntu/Debian..."

# Create virtual host configuration
cat > /tmp/app.conf << 'EOF'
<VirtualHost *:80>
    DocumentRoot {document_root}
    
    <Directory {document_root}>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
    
    # Enable rewrite engine for pretty URLs
    RewriteEngine On
    
    # Security headers
    Header always set X-Content-Type-Options nosniff
    Header always set X-Frame-Options DENY
    Header always set X-XSS-Protection "1; mode=block"
    
    ErrorLog /var/log/apache2/app_error.log
    CustomLog /var/log/apache2/app_access.log combined
</VirtualHost>
EOF

# Install the configuration
sudo mv /tmp/app.conf /etc/apache2/sites-available/app.conf
sudo a2ensite app.conf
sudo a2dissite 000-default.conf || true

# Enable required modules
sudo a2enmod rewrite
sudo a2enmod headers

# Ensure proper permissions
sudo chown -R {web_user}:{web_group} {document_root}
sudo chmod -R 755 {document_root}

echo "✅ Apache configured for application on Ubuntu/Debian"
'''
        else:
            # Amazon Linux/RHEL/CentOS Apache configuration
            script = f'''
set -e
echo "Configuring Apache for application on Amazon Linux/RHEL/CentOS..."

# Create virtual host configuration
cat > /tmp/app.conf << 'EOF'
<VirtualHost *:80>
    DocumentRoot {document_root}
    
    <Directory {document_root}>
        Options Indexes FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>
    
    # Enable rewrite engine for pretty URLs
    RewriteEngine On
    
    # Security headers
    Header always set X-Content-Type-Options nosniff
    Header always set X-Frame-Options DENY
    Header always set X-XSS-Protection "1; mode=block"
    
    ErrorLog /var/log/httpd/app_error.log
    CustomLog /var/log/httpd/app_access.log combined
</VirtualHost>
EOF

# Install the configuration
sudo mv /tmp/app.conf /etc/httpd/conf.d/app.conf

# Ensure proper permissions
sudo chown -R {web_user}:{web_group} {document_root}
sudo chmod -R 755 {document_root}

# Create a simple index.html if none exists
if [ ! -f {document_root}/index.html ] && [ ! -f {document_root}/index.php ]; then
    cat > /tmp/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>Application Deployed Successfully</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .success {{ color: #28a745; }}
        .info {{ background: #f8f9fa; padding: 20px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1 class="success">✅ Application Deployed Successfully!</h1>
    <div class="info">
        <p><strong>Server:</strong> Apache on Amazon Linux</p>
        <p><strong>Document Root:</strong> {document_root}</p>
        <p><strong>Status:</strong> Web server is running and accessible</p>
    </div>
    <p>Your application has been deployed successfully. You can now upload your application files to {document_root}.</p>
</body>
</html>
EOF
    sudo mv /tmp/index.html {document_root}/index.html
    sudo chown {web_user}:{web_group} {document_root}/index.html
    sudo chmod 644 {document_root}/index.html
    echo "✅ Created default index.html"
fi

# Restart Apache to apply configuration
sudo systemctl restart httpd

echo "✅ Apache configured for application on Amazon Linux/RHEL/CentOS"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        print(output)
        return success
