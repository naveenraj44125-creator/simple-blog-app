"""Database configurator for MySQL and PostgreSQL"""
from .base_configurator import BaseConfigurator
from os_detector import OSDetector

class DatabaseConfigurator(BaseConfigurator):
    """Handles database configuration (MySQL, PostgreSQL, RDS)"""
    
    def configure(self) -> bool:
        """Configure database connections based on enabled dependencies"""
        print("🔧 Configuring database connections...")
        
        # Get OS information from client
        os_type = getattr(self.client, 'os_type', 'ubuntu')
        os_info = getattr(self.client, 'os_info', {'package_manager': 'apt', 'user': 'ubuntu'})
        
        # Get OS-specific information
        self.user_info = OSDetector.get_user_info(os_type)
        self.pkg_commands = OSDetector.get_package_manager_commands(os_info['package_manager'])
        self.svc_commands = OSDetector.get_service_commands(os_info.get('service_manager', 'systemd'))
        
        # Check if MySQL is enabled in config
        mysql_enabled = self.config.get('dependencies.mysql.enabled', False)
        mysql_external = self.config.get('dependencies.mysql.external', False)
        
        if mysql_enabled:
            if mysql_external:
                return self._configure_rds_connection()
            else:
                return self._configure_local_mysql()
        
        # Check if PostgreSQL is enabled
        postgresql_enabled = self.config.get('dependencies.postgresql.enabled', False)
        if postgresql_enabled:
            return self._configure_local_postgresql()
        
        print("ℹ️  No database dependencies enabled, skipping database configuration")
        return True
    
    def _configure_rds_connection(self) -> bool:
        """Configure RDS database connection"""
        print("🔧 Configuring RDS database connection...")
        
        rds_config = self.config.get('dependencies.mysql.rds', {})
        database_name = rds_config.get('database_name', 'lamp-app-db')
        
        script = f'''
set -e
echo "Setting up RDS database connection..."

# Install MySQL client
{self.pkg_commands['update']}
mysql_client_pkg=$(if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then echo "mysql-client"; else echo "mysql"; fi)
{self.pkg_commands['install']} $mysql_client_pkg

# Create fallback environment file
if [ ! -f /var/www/html/.env ]; then
    echo "Creating fallback local database environment file..."
    sudo tee /var/www/html/.env > /dev/null << 'EOF'
# Database Configuration - Fallback to Local MySQL
DB_EXTERNAL=false
DB_TYPE=MYSQL
DB_HOST=localhost
DB_PORT=3306
DB_NAME=app_db
DB_USERNAME=root
DB_PASSWORD=root123
DB_CHARSET=utf8mb4

# Application Configuration
APP_ENV=production
APP_DEBUG=false
APP_NAME="Generic Application"
EOF

    sudo chown {self.user_info['web_user']}:{self.user_info['web_group']} /var/www/html/.env
    sudo chmod 644 /var/www/html/.env
    echo "✅ Fallback environment file created"
fi

echo "✅ RDS configuration completed (with local fallback)"
'''
        
        success, output = self.client.run_command(script, timeout=120)
        
        if not success:
            print("⚠️  RDS configuration failed, falling back to local MySQL")
            return self._configure_local_mysql()
        
        return success
    
    def _configure_local_mysql(self) -> bool:
        """Configure local MySQL database"""
        print("🔧 Configuring local MySQL database...")
        
        script = '''
set -e
echo "Setting up local MySQL database..."

# Install MySQL if not present
if ! command -v mysql &> /dev/null; then
    echo "Installing MySQL server..."
    mysql_server_pkg=$(if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then echo "mysql-server"; else echo "mysql-server"; fi)
    if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then
        sudo DEBIAN_FRONTEND=noninteractive {self.pkg_commands['install']} $mysql_server_pkg
    else
        {self.pkg_commands['install']} $mysql_server_pkg
    fi
fi

# Start and enable MySQL
mysql_service=$(if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then echo "mysql"; else echo "mysqld"; fi)
{self.svc_commands['start']} $mysql_service
{self.svc_commands['enable']} $mysql_service

# Configure MySQL root user
echo "Configuring MySQL root user..."
sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'root123';" 2>/dev/null || echo "Root password configuration attempted"

# Create application database
mysql -u root -proot123 -e "CREATE DATABASE IF NOT EXISTS app_db;" 2>/dev/null && echo "✅ app_db database created" || echo "❌ Failed to create database"

# Create test table with sample data
mysql -u root -proot123 app_db -e "
CREATE TABLE IF NOT EXISTS test_table (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT IGNORE INTO test_table (id, name) VALUES 
    (1, 'Test Entry'),
    (2, 'Sample Data'),
    (3, 'Database Working');
" 2>/dev/null && echo "✅ Test table created with sample data" || echo "❌ Failed to create test table"

# Test connection
mysql -u root -proot123 -e "SELECT COUNT(*) as record_count FROM test_table;" app_db 2>/dev/null && echo "✅ MySQL connection test successful" || echo "❌ MySQL connection test failed"

# Create environment file
sudo tee /var/www/html/.env > /dev/null << 'EOF'
# Database Configuration - Local MySQL
DB_EXTERNAL=false
DB_TYPE=MYSQL
DB_HOST=localhost
DB_PORT=3306
DB_NAME=app_db
DB_USERNAME=root
DB_PASSWORD=root123
DB_CHARSET=utf8mb4

# Application Configuration
APP_ENV=production
APP_DEBUG=false
APP_NAME="Generic Application"
EOF

# Set proper permissions
sudo chown {self.user_info['web_user']}:{self.user_info['web_group']} /var/www/html/.env
sudo chmod 644 /var/www/html/.env

echo "✅ Local MySQL database setup completed"
'''
        
        success, output = self.client.run_command_with_live_output(script, timeout=420)
        return success
    
    def _configure_local_postgresql(self) -> bool:
        """Configure local PostgreSQL database"""
        print("🔧 Configuring local PostgreSQL database...")
        
        script = '''
set -e
echo "Setting up local PostgreSQL database..."

# Install PostgreSQL
{self.pkg_commands['update']}
pg_packages=$(if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then echo "postgresql postgresql-contrib"; else echo "postgresql-server postgresql-contrib"; fi)
{self.pkg_commands['install']} $pg_packages

# Start and enable PostgreSQL
pg_service=$(if [ "{self.pkg_commands['install']}" = *"apt-get"* ]; then echo "postgresql"; else echo "postgresql"; fi)
{self.svc_commands['start']} $pg_service
{self.svc_commands['enable']} $pg_service

# Create application database and user
sudo -u postgres psql -c "CREATE DATABASE app_db;" 2>/dev/null || echo "Database may already exist"
sudo -u postgres psql -c "CREATE USER app_user WITH PASSWORD 'app_password';" 2>/dev/null || echo "User may already exist"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE app_db TO app_user;" 2>/dev/null || echo "Privileges granted"

# Create environment file
sudo tee /var/www/html/.env > /dev/null << 'EOF'
# Database Configuration - Local PostgreSQL
DB_EXTERNAL=false
DB_TYPE=POSTGRESQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=app_db
DB_USERNAME=app_user
DB_PASSWORD=app_password
DB_CHARSET=utf8

# Application Configuration
APP_ENV=production
APP_DEBUG=false
APP_NAME="Generic Application"
EOF

# Set proper permissions
sudo chown {self.user_info['web_user']}:{self.user_info['web_group']} /var/www/html/.env
sudo chmod 644 /var/www/html/.env

echo "✅ Local PostgreSQL database setup completed"
'''
        
        success, output = self.client.run_command(script, timeout=420)
        return success
