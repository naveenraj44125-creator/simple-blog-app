"""PHP configurator"""

from .base_configurator import BaseConfigurator


class PhpConfigurator(BaseConfigurator):
    """Configure PHP for the application"""
    
    def configure(self) -> bool:
        """Configure PHP for the application"""
        print("🔧 Configuring PHP...")
        
        script = '''
set -e
echo "Configuring PHP for application..."

# Configure PHP settings for production
PHP_INI="/etc/php/8.1/apache2/php.ini"
if [ -f "$PHP_INI" ]; then
    sudo sed -i 's/display_errors = On/display_errors = Off/' "$PHP_INI"
    sudo sed -i 's/;date.timezone =/date.timezone = UTC/' "$PHP_INI"
    sudo sed -i 's/upload_max_filesize = 2M/upload_max_filesize = 10M/' "$PHP_INI"
    sudo sed -i 's/post_max_size = 8M/post_max_size = 10M/' "$PHP_INI"
fi

# Configure PHP-FPM if available
PHP_FPM_INI="/etc/php/8.1/fpm/php.ini"
if [ -f "$PHP_FPM_INI" ]; then
    sudo sed -i 's/display_errors = On/display_errors = Off/' "$PHP_FPM_INI"
    sudo sed -i 's/;date.timezone =/date.timezone = UTC/' "$PHP_FPM_INI"
fi

echo "✅ PHP configured for application"
'''
        
        success, output = self.client.run_command(script, timeout=60)
        print(output)
        return success
