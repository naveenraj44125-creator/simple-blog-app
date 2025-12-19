"""Docker application configurator"""
from .base_configurator import BaseConfigurator
from os_detector import OSDetector
import os

class DockerConfigurator(BaseConfigurator):
    """Handles Docker-based application deployment"""
    
    def configure(self) -> bool:
        """Deploy application using Docker and docker-compose"""
        print("🐳 Deploying application with Docker...")
        
        # This is handled separately in _deploy_with_docker
        # This configurator is a placeholder for future Docker-specific configurations
        return True
    
    def deploy_with_docker(self, package_file, env_vars=None) -> bool:
        """Deploy application using Docker and docker-compose"""
        print("🐳 Deploying application with Docker...")
        
        # Get OS information from client
        os_type = getattr(self.client, 'os_type', 'ubuntu')
        os_info = getattr(self.client, 'os_info', {'package_manager': 'apt', 'user': 'ubuntu'})
        
        # Get OS-specific information
        self.user_info = OSDetector.get_user_info(os_type)
        self.pkg_commands = OSDetector.get_package_manager_commands(os_info['package_manager'])
        
        # Check if using pre-built image
        docker_image_tag = os.environ.get('DOCKER_IMAGE_TAG', '')
        use_prebuilt_image = bool(docker_image_tag)
        
        if use_prebuilt_image:
            print(f"📦 Using pre-built Docker image: {docker_image_tag}")
        else:
            print("🔨 Will build Docker image on instance")
        
        # Upload package to instance
        print(f"📤 Uploading package file {package_file}...")
        remote_package_path = f"~/{package_file}"
        
        if not self.client.copy_file_to_instance(package_file, remote_package_path):
            print(f"❌ Failed to upload package file")
            return False
        
        # Prepare environment variables for docker-compose
        env_file_content = ""
        if env_vars:
            for key, value in env_vars.items():
                env_file_content += f'{key}={value}\n'
        
        script = f'''
set -e
echo "🐳 Setting up Docker deployment..."

# Set Docker image tag if provided
export DOCKER_IMAGE_TAG="{docker_image_tag}"

# Create deployment directory
DEPLOY_DIR="/opt/docker-app"
sudo mkdir -p $DEPLOY_DIR
cd $DEPLOY_DIR

# Extract application package
echo "📦 Extracting application..."
sudo tar -xzf ~/{package_file} -C $DEPLOY_DIR

# Find docker-compose file
COMPOSE_FILE=$(find . -name "docker-compose.yml" -o -name "docker-compose.yaml" | head -n 1)

if [ -z "$COMPOSE_FILE" ]; then
    echo "❌ No docker-compose.yml found in package"
    exit 1
fi

echo "✅ Found docker-compose file: $COMPOSE_FILE"

# Create .env file if environment variables provided
if [ -n "{env_file_content}" ]; then
    sudo tee .env > /dev/null << 'ENVEOF'
{env_file_content}
ENVEOF
    echo "✅ Environment file created"
fi

# Ensure Docker is available
DOCKER_BIN=""
if [ -f /usr/bin/docker ]; then
    DOCKER_BIN="/usr/bin/docker"
elif command -v docker > /dev/null 2>&1; then
    DOCKER_BIN=$(command -v docker)
else
    echo "⚠️  Docker not found, attempting to install..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
    sudo systemctl start docker
    sudo systemctl enable docker
    
    if [ -f /usr/bin/docker ]; then
        DOCKER_BIN="/usr/bin/docker"
    elif command -v docker > /dev/null 2>&1; then
        DOCKER_BIN=$(command -v docker)
    else
        echo "❌ Docker installation failed"
        exit 1
    fi
    echo "✅ Docker installed successfully"
fi

echo "✅ Docker found at $DOCKER_BIN"

# Add default user to docker group
sudo usermod -aG docker {self.user_info['default_user']} || true

# Stop existing containers
echo "🛑 Stopping existing containers..."
sudo $DOCKER_BIN compose -f $COMPOSE_FILE down --timeout 30 || true

# Pull or build images
if [ -n "$DOCKER_IMAGE_TAG" ]; then
    echo "📦 Using pre-built image: $DOCKER_IMAGE_TAG"
    export DOCKER_IMAGE="$DOCKER_IMAGE_TAG"
    
    # Pull the pre-built image with retry logic
    echo "📥 Pulling pre-built Docker image..."
    PULL_SUCCESS=false
    for attempt in 1 2 3; do
        echo "Attempt $attempt/3 to pull image..."
        if timeout 600 sudo $DOCKER_BIN pull "$DOCKER_IMAGE_TAG"; then
            echo "✅ Image pulled successfully"
            PULL_SUCCESS=true
            break
        else
            echo "⚠️  Pull attempt $attempt failed"
            [ $attempt -lt 3 ] && sleep 10
        fi
    done
    
    if [ "$PULL_SUCCESS" = "false" ]; then
        echo "❌ Failed to pull image after 3 attempts"
        exit 1
    fi
    
    # Pull service images
    timeout 600 sudo $DOCKER_BIN compose -f $COMPOSE_FILE pull db redis phpmyadmin 2>/dev/null || true
else
    echo "🔨 Building Docker image on instance..."
    timeout 600 sudo $DOCKER_BIN compose -f $COMPOSE_FILE pull || true
    
    if grep -q "build:" $COMPOSE_FILE; then
        timeout 900 sudo $DOCKER_BIN compose -f $COMPOSE_FILE build || {{
            echo "❌ Build failed"
            sudo $DOCKER_BIN compose -f $COMPOSE_FILE logs --tail=100
            exit 1
        }}
    fi
fi

# Start containers
echo "🚀 Starting containers..."
timeout 300 sudo $DOCKER_BIN compose -f $COMPOSE_FILE up -d || {{
    echo "❌ Failed to start containers"
    sudo $DOCKER_BIN compose -f $COMPOSE_FILE ps -a
    sudo $DOCKER_BIN compose -f $COMPOSE_FILE logs --tail=100
    exit 1
}}

# Wait for containers to initialize
echo "⏳ Waiting for containers to initialize..."
sleep 30

# Check container status
echo "📊 Container status:"
sudo $DOCKER_BIN compose -f $COMPOSE_FILE ps

# Test web service connectivity
echo "🔍 Testing web service..."
WEB_READY=false
for i in {{1..20}}; do
    if curl -f -s --connect-timeout 5 http://localhost/ > /dev/null 2>&1; then
        echo "✅ Web service is responding"
        WEB_READY=true
        break
    fi
    echo "Waiting for web service... ($i/20)"
    sleep 5
done

if [ "$WEB_READY" = "false" ]; then
    echo "⚠️  Web service not responding after 100 seconds"
    sudo $DOCKER_BIN compose -f $COMPOSE_FILE ps
    sudo $DOCKER_BIN compose -f $COMPOSE_FILE logs --tail=50
fi

echo "✅ Docker deployment completed"
'''
        
        success, output = self.client.run_command(script, timeout=1200)
        print(output)
        
        if not success:
            print("❌ Docker deployment failed")
            return False
        
        print("✅ Application deployed with Docker successfully")
        return True
