#!/usr/bin/env python3
"""
Lightsail RDS Manager for AWS Lightsail Deployments
This module handles Lightsail RDS database operations and connectivity
"""

import boto3
import sys
import time
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError, NoCredentialsError
from lightsail_common import LightsailBase

class LightsailRDSManager(LightsailBase):
    """Manager for Lightsail RDS database operations"""
    
    def __init__(self, instance_name, region='us-east-1', aws_access_key_id=None, aws_secret_access_key=None):
        super().__init__(instance_name, region)
        
        # Initialize Lightsail client with credentials if provided
        if aws_access_key_id and aws_secret_access_key:
            self.lightsail = boto3.client(
                'lightsail',
                region_name=region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key
            )
        
    def get_rds_connection_details(self, rds_instance_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve RDS instance connection details from Lightsail
        
        Args:
            rds_instance_name (str): Name of the Lightsail RDS instance
            
        Returns:
            dict: Connection details including endpoint, port, credentials
        """
        try:
            print(f"🔍 Retrieving RDS instance details for: {rds_instance_name}")
            
            # Get RDS instance details
            response = self.lightsail.get_relational_database(
                relationalDatabaseName=rds_instance_name
            )
            
            db_instance = response['relationalDatabase']
            
            # Check if instance is available
            if db_instance['state'] != 'available':
                print(f"⚠️  RDS instance is in '{db_instance['state']}' state, not 'available'")
                return None
            
            # Get master user password (if available)
            master_password = None
            try:
                password_response = self.lightsail.get_relational_database_master_user_password(
                    relationalDatabaseName=rds_instance_name
                )
                master_password = password_response.get('masterUserPassword')
                print("✅ Retrieved master password from Lightsail")
            except ClientError as e:
                print(f"⚠️  Could not retrieve master password: {e}")
                print("   You may need to set a password manually or use environment variables")
            
            connection_details = {
                'endpoint': db_instance['masterEndpoint']['address'],
                'port': db_instance['masterEndpoint']['port'],
                'engine': db_instance['engine'],
                'engine_version': db_instance['engineVersion'],
                'master_username': db_instance['masterUsername'],
                'master_password': master_password,
                'database_name': db_instance.get('masterDatabaseName', 'mysql'),
                'state': db_instance['state'],
                'instance_name': rds_instance_name
            }
            
            print(f"✅ RDS connection details retrieved:")
            print(f"   Endpoint: {connection_details['endpoint']}")
            print(f"   Port: {connection_details['port']}")
            print(f"   Engine: {connection_details['engine']} {connection_details['engine_version']}")
            print(f"   Master DB: {connection_details['database_name']}")
            
            return connection_details
            
        except ClientError as e:
            print(f"❌ Error retrieving RDS details: {e}")
            return None
    
    def wait_for_rds_available(self, rds_instance_name: str, timeout: int = 600) -> bool:
        """
        Wait for RDS instance to be in 'available' state
        
        Args:
            rds_instance_name (str): Name of the RDS instance
            timeout (int): Maximum wait time in seconds
            
        Returns:
            bool: True if instance becomes available
        """
        print(f"⏳ Waiting for RDS instance {rds_instance_name} to be available...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = self.lightsail.get_relational_database(
                    relationalDatabaseName=rds_instance_name
                )
                
                current_state = response['relationalDatabase']['state']
                print(f"   RDS state: {current_state}")
                
                if current_state == 'available':
                    print(f"✅ RDS instance is available")
                    return True
                elif current_state in ['failed', 'incompatible-restore', 'incompatible-network']:
                    print(f"❌ RDS instance is in failed state: {current_state}")
                    return False
                    
                time.sleep(30)  # Check every 30 seconds
                
            except ClientError as e:
                print(f"❌ Error checking RDS state: {e}")
                return False
        
        print(f"❌ Timeout waiting for RDS instance to be available")
        return False
    
    def test_rds_connectivity(self, connection_details: Dict[str, Any], database_name: str = None) -> bool:
        """
        Test connectivity to RDS instance from Lightsail instance
        
        Args:
            connection_details (dict): RDS connection details
            database_name (str): Specific database to test
            
        Returns:
            bool: True if connection successful
        """
        if not connection_details:
            print("❌ No connection details provided")
            return False
            
        engine = connection_details['engine']
        endpoint = connection_details['endpoint']
        port = connection_details['port']
        username = connection_details['master_username']
        password = connection_details['master_password']
        db_name = database_name or connection_details['database_name']
        
        print(f"🔍 Testing connectivity to {engine} RDS instance...")
        
        if not password:
            print("⚠️  No password available - connectivity test may fail")
            return False
        
        if engine.startswith('mysql'):
            return self._test_mysql_connection(endpoint, port, username, password, db_name)
        elif engine.startswith('postgres'):
            return self._test_postgres_connection(endpoint, port, username, password, db_name)
        else:
            print(f"⚠️  Unsupported database engine: {engine}")
            return False
    
    def _test_mysql_connection(self, host: str, port: int, username: str, password: str, database: str) -> bool:
        """Test MySQL connection from Lightsail instance"""
        test_script = f'''
set -e
echo "Testing MySQL connection to {host}:{port}..."

# Install MySQL client if not present
if ! command -v mysql &> /dev/null; then
    echo "Installing MySQL client..."
    sudo apt-get update -qq
    sudo apt-get install -y mysql-client
fi

# Test connection with timeout
timeout 30 mysql -h {host} -P {port} -u {username} -p{password} -e "SELECT 1 as test_connection;" {database}

if [ $? -eq 0 ]; then
    echo "✅ MySQL connection successful"
    exit 0
else
    echo "❌ MySQL connection failed"
    exit 1
fi
'''
        
        success, output = self.run_command(test_script, timeout=60)
        return success
    
    def _test_postgres_connection(self, host: str, port: int, username: str, password: str, database: str) -> bool:
        """Test PostgreSQL connection from Lightsail instance"""
        test_script = f'''
set -e
echo "Testing PostgreSQL connection to {host}:{port}..."

# Install PostgreSQL client if not present
if ! command -v psql &> /dev/null; then
    echo "Installing PostgreSQL client..."
    sudo apt-get update -qq
    sudo apt-get install -y postgresql-client
fi

# Test connection with timeout
timeout 30 env PGPASSWORD={password} psql -h {host} -p {port} -U {username} -d {database} -c "SELECT 1 as test_connection;"

if [ $? -eq 0 ]; then
    echo "✅ PostgreSQL connection successful"
    exit 0
else
    echo "❌ PostgreSQL connection failed"
    exit 1
fi
'''
        
        success, output = self.run_command(test_script, timeout=60)
        return success
    
    def install_database_client(self, connection_details: Dict[str, Any], app_database_name: str = None) -> bool:
        """
        Install database client and configure connection for application
        
        Args:
            connection_details (dict): RDS connection details
            app_database_name (str): Application database name
            
        Returns:
            bool: True if successful
        """
        engine = connection_details['engine']
        app_db = app_database_name or 'appdb'
        
        if engine.startswith('mysql'):
            return self._install_mysql_client(connection_details, app_db)
        elif engine.startswith('postgres'):
            return self._install_postgres_client(connection_details, app_db)
        else:
            print(f"⚠️  Unsupported database engine: {engine}")
            return False
    
    def _install_mysql_client(self, connection_details: Dict[str, Any], database_name: str) -> bool:
        """Install MySQL client and configure connection"""
        endpoint = connection_details['endpoint']
        port = connection_details['port']
        username = connection_details['master_username']
        password = connection_details['master_password']
        
        script = f'''
set -e
echo "Installing MySQL client for external RDS..."

# Install MySQL client
sudo apt-get update -qq
sudo apt-get install -y mysql-client

# Create application database connection config directory
sudo mkdir -p /etc/mysql/conf.d

# Create connection configuration file
cat << 'EOF' | sudo tee /etc/mysql/conf.d/app.cnf
[client]
host={endpoint}
port={port}
user={username}
password={password}
database={database_name}
EOF

# Set secure permissions
sudo chmod 600 /etc/mysql/conf.d/app.cnf
sudo chown root:root /etc/mysql/conf.d/app.cnf

# Create application database if it doesn't exist
echo "Creating application database if needed..."
mysql -h {endpoint} -P {port} -u {username} -p{password} -e "CREATE DATABASE IF NOT EXISTS {database_name};" || true

echo "✅ MySQL client configured for RDS"
'''
        
        success, output = self.run_command(script, timeout=420)
        return success
    
    def _install_postgres_client(self, connection_details: Dict[str, Any], database_name: str) -> bool:
        """Install PostgreSQL client and configure connection"""
        endpoint = connection_details['endpoint']
        port = connection_details['port']
        username = connection_details['master_username']
        password = connection_details['master_password']
        
        script = f'''
set -e
echo "Installing PostgreSQL client for external RDS..."

# Install PostgreSQL client
sudo apt-get update -qq
sudo apt-get install -y postgresql-client

# Create application database connection config
sudo mkdir -p /etc/postgresql

# Create .pgpass file for password-less connections
cat << 'EOF' | sudo tee /etc/postgresql/.pgpass
{endpoint}:{port}:*:{username}:{password}
EOF

sudo chmod 600 /etc/postgresql/.pgpass
sudo chown root:root /etc/postgresql/.pgpass

# Create application database if it doesn't exist
echo "Creating application database if needed..."
PGPASSWORD={password} createdb -h {endpoint} -p {port} -U {username} {database_name} || true

echo "✅ PostgreSQL client configured for RDS"
'''
        
        success, output = self.run_command(script, timeout=420)
        return success
    
    def create_database_env_vars(self, connection_details: Dict[str, Any], database_name: str) -> Dict[str, str]:
        """
        Create environment variables for application database connection
        
        Args:
            connection_details (dict): RDS connection details
            database_name (str): Application database name
            
        Returns:
            dict: Environment variables for database connection
        """
        engine = connection_details['engine']
        db_type = 'MYSQL' if engine.startswith('mysql') else 'POSTGRESQL' if engine.startswith('postgres') else engine.upper()
        
        return {
            'DB_TYPE': db_type,
            'DB_HOST': connection_details['endpoint'],
            'DB_PORT': str(connection_details['port']),
            'DB_NAME': database_name,
            'DB_USERNAME': connection_details['master_username'],
            'DB_PASSWORD': connection_details['master_password'] or '',
            'DB_CHARSET': 'utf8mb4',
            'DB_EXTERNAL': 'true',
            'DATABASE_URL': self._build_database_url(connection_details, database_name)
        }
    
    def _build_database_url(self, connection_details: Dict[str, Any], database_name: str) -> str:
        """Build database connection URL"""
        engine = connection_details['engine']
        host = connection_details['endpoint']
        port = connection_details['port']
        username = connection_details['master_username']
        password = connection_details['master_password'] or ''
        
        if engine.startswith('mysql'):
            return f"mysql://{username}:{password}@{host}:{port}/{database_name}"
        elif engine.startswith('postgres'):
            return f"postgresql://{username}:{password}@{host}:{port}/{database_name}"
        else:
            return f"{engine}://{username}:{password}@{host}:{port}/{database_name}"
