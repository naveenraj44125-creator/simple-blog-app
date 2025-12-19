#!/usr/bin/env python3
"""
Instance Setup Script for GitHub Actions Deployment
Handles instance creation, OS detection, Docker validation, firewall setup, and bucket configuration
"""

import yaml
import os
import sys
import boto3
import time
from os_detector import OSDetector

def main():
    """Main setup function with full functionality from embedded script"""
    try:
        # Get inputs from environment variables (set by GitHub Actions)
        config_file = os.environ.get('CONFIG_FILE', 'deployment-generic.config.yml')
        instance_name_override = os.environ.get('INSTANCE_NAME', '')
        aws_region_override = os.environ.get('AWS_REGION', '')
        
        print(f"🔧 Loading configuration from {config_file}...")
        
        # Load configuration
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract values from config (allow input overrides)
        instance_name = instance_name_override or config['lightsail']['instance_name']
        aws_region = aws_region_override or config['aws']['region']
        app_name = config['application']['name']
        app_type = config['application']['type']
        app_version = config['application']['version']
        
        print(f"✅ Instance Name: {instance_name}")
        print(f"✅ AWS Region: {aws_region}")
        print(f"✅ Application: {app_name} v{app_version}")
        print(f"✅ App Type: {app_type}")
        
        # Initialize Lightsail client
        lightsail = boto3.client('lightsail', region_name=aws_region)
        
        # Initialize OS detection variables (will be set based on instance blueprint)
        os_type = 'unknown'
        package_manager = 'unknown'
        
        # Check if instance exists, create if not
        static_ip = ""
        instance_exists = False
        
        try:
            print(f"\n🔍 Checking if instance '{instance_name}' exists...")
            response = lightsail.get_instance(instanceName=instance_name)
            instance = response['instance']
            instance_exists = True
            print(f"✅ Instance '{instance_name}' already exists with state: {instance['state']['name']}")
            
            # Detect operating system from blueprint
            blueprint_id = instance.get('blueprintId', '')
            blueprint_name = instance.get('blueprintName', '')
            print(f"📋 Blueprint: {blueprint_name} ({blueprint_id})")
            
            # Use OSDetector for OS detection
            detector = OSDetector()
            os_type, os_info = detector.detect_os_from_blueprint(blueprint_id)
            package_manager = os_info['package_manager']
            print(f"✅ {os_type.title()} OS detected: {blueprint_name}")
            print(f"🔧 Package manager: {package_manager}")
            
            # Validate instance size for Docker deployments
            docker_enabled = config.get('dependencies', {}).get('docker', {}).get('enabled', False)
            use_docker = config.get('deployment', {}).get('use_docker', False)
            
            if docker_enabled and use_docker:
                ram_gb = instance.get('hardware', {}).get('ramSizeInGb', 0)
                bundle_id = instance.get('bundleId', '')
                
                print(f"\n🐳 Docker deployment detected - validating instance size...")
                print(f"   Instance RAM: {ram_gb} GB")
                print(f"   Bundle ID: {bundle_id}")
                
                # Docker requires minimum 2GB RAM for reliable operation
                MIN_DOCKER_RAM = 2.0
                
                if ram_gb < MIN_DOCKER_RAM:
                    print(f"❌ ERROR: Instance has insufficient RAM for Docker deployment!")
                    print(f"   Current RAM: {ram_gb} GB")
                    print(f"   Required RAM: {MIN_DOCKER_RAM} GB minimum")
                    print(f"   Current bundle: {bundle_id}")
                    print(f"\n💡 Recommended bundles for Docker:")
                    print(f"   - small_3_0 (2GB RAM, $12/month)")
                    print(f"   - medium_3_0 (4GB RAM, $24/month)")
                    print(f"   - large_3_0 (8GB RAM, $44/month)")
                    print(f"\n⚠️  Deployment will be SKIPPED to prevent instance freezing.")
                    print(f"   Please upgrade your instance size and try again.")
                    
                    # Write GitHub Actions summary
                    if 'GITHUB_STEP_SUMMARY' in os.environ:
                        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                            f.write(f"## ❌ Docker Deployment Blocked - Insufficient RAM\n\n")
                            f.write(f"**Instance:** `{instance_name}`\n\n")
                            f.write(f"**Current Configuration:**\n")
                            f.write(f"- RAM: {ram_gb} GB\n")
                            f.write(f"- Bundle: `{bundle_id}`\n\n")
                            f.write(f"**Required Configuration:**\n")
                            f.write(f"- Minimum RAM: {MIN_DOCKER_RAM} GB\n\n")
                            f.write(f"### 💡 Recommended Actions\n\n")
                            f.write(f"Docker requires at least 2GB RAM to operate reliably. Please upgrade your instance:\n\n")
                            f.write(f"| Bundle | RAM | CPU | Storage | Price/Month |\n")
                            f.write(f"|--------|-----|-----|---------|-------------|\n")
                            f.write(f"| `small_3_0` | 2 GB | 2 vCPU | 60 GB | $12 |\n")
                            f.write(f"| `medium_3_0` | 4 GB | 2 vCPU | 80 GB | $24 |\n")
                            f.write(f"| `large_3_0` | 8 GB | 2 vCPU | 160 GB | $44 |\n\n")
                    
                    # Set outputs and exit
                    if 'GITHUB_OUTPUT' in os.environ:
                        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                            f.write(f"instance_name={instance_name}\n")
                            f.write(f"aws_region={aws_region}\n")
                            f.write(f"app_name={app_name}\n")
                            f.write(f"app_type={app_type}\n")
                            f.write(f"app_version={app_version}\n")
                            f.write(f"should_deploy=false\n")
                    sys.exit(1)
                else:
                    print(f"✅ Instance size validated: {ram_gb} GB RAM is sufficient for Docker")
            else:
                print(f"\nℹ️  Non-Docker deployment - no minimum RAM requirement")
            
            # Get public IP from existing instance
            if 'publicIpAddress' in instance:
                static_ip = instance['publicIpAddress']
                print(f"✅ Using existing instance public IP: {static_ip}")
            else:
                print("⚠️  No public IP found on existing instance")
            
            # Ensure firewall ports are open for existing instances
            print("\n🔥 Ensuring firewall ports are open on existing instance...")
            
            # Get custom ports from config
            firewall_config = config.get('dependencies', {}).get('firewall', {}).get('config', {})
            allowed_ports = firewall_config.get('allowed_ports', ['22', '80', '443'])
            
            # Convert to port info format
            port_infos = []
            for port in allowed_ports:
                port_num = int(str(port).strip())
                port_infos.append({'fromPort': port_num, 'toPort': port_num, 'protocol': 'tcp'})
            
            print(f"   Ensuring ports are open: {', '.join(map(str, allowed_ports))}")
            
            try:
                lightsail.put_instance_public_ports(
                    portInfos=port_infos,
                    instanceName=instance_name
                )
                print(f"✅ Firewall ports ensured: {', '.join(map(str, allowed_ports))}")
            except Exception as e:
                print(f"⚠️  Could not update firewall: {e}")
            
            # Setup Lightsail bucket if configured for existing instance
            bucket_config = config.get('lightsail', {}).get('bucket', {})
            if bucket_config.get('enabled', False):
                bucket_name = bucket_config.get('name', '')
                if bucket_name:
                    print(f"\n🪣 Setting up Lightsail bucket for existing instance...")
                    try:
                        sys.path.insert(0, 'workflows')
                        from lightsail_bucket import LightsailBucket
                        
                        bucket_manager = LightsailBucket(region=aws_region)
                        access_level = bucket_config.get('access_level', 'read_only')
                        bundle_id_bucket = bucket_config.get('bundle_id', 'small_1_0')
                        
                        success, message = bucket_manager.setup_bucket_for_instance(
                            bucket_name=bucket_name,
                            instance_name=instance_name,
                            access_level=access_level,
                            bundle_id=bundle_id_bucket,
                            create_if_missing=True
                        )
                        
                        if success:
                            print(f"✅ {message}")
                        else:
                            print(f"⚠️  {message}")
                    except ImportError:
                        print("⚠️  Bucket configuration requested but lightsail_bucket module not available")
                else:
                    print("⚠️  Bucket enabled but no name specified")
            else:
                print("\nℹ️  Lightsail bucket not configured")
                
        except lightsail.exceptions.NotFoundException:
            print(f"⚠️  Instance '{instance_name}' not found. Creating new instance...")
            instance_exists = False
            
            # Determine bundle size - check config first, then deployment type
            docker_enabled = config.get('dependencies', {}).get('docker', {}).get('enabled', False)
            use_docker = config.get('deployment', {}).get('use_docker', False)
            
            # Check if bundle_id is specified in config
            config_bundle_id = config.get('lightsail', {}).get('bundle_id', '')
            
            if config_bundle_id:
                bundle_id = config_bundle_id
                print(f"📋 Using configured bundle: {bundle_id}")
                
                # Validate bundle for Docker deployments
                if docker_enabled and use_docker:
                    docker_compatible_bundles = ['small_3_0', 'medium_3_0', 'large_3_0', 'xlarge_3_0', '2xlarge_3_0']
                    if bundle_id not in docker_compatible_bundles:
                        print(f"⚠️  WARNING: Bundle '{bundle_id}' may not have enough RAM for Docker!")
                        print(f"   Recommended Docker bundles: {', '.join(docker_compatible_bundles)}")
                        print(f"   Proceeding with configured bundle...")
            elif docker_enabled and use_docker:
                bundle_id = 'medium_3_0'  # 4 GB RAM for better Docker performance
                print(f"🐳 Docker deployment detected - using default bundle: {bundle_id} (4GB RAM)")
            else:
                bundle_id = 'small_3_0'  # 2 GB RAM for traditional deployments
                print(f"📦 Traditional deployment - using default bundle: {bundle_id} (2GB RAM)")
            
            # Check if blueprint_id is specified in config
            config_blueprint_id = config.get('lightsail', {}).get('blueprint_id', '')
            
            if config_blueprint_id:
                blueprint_id = config_blueprint_id
                print(f"📋 Using configured blueprint: {blueprint_id}")
            else:
                blueprint_id = 'ubuntu_22_04'  # Default to Ubuntu 22.04
                print(f"📋 Using default blueprint: {blueprint_id}")
            
            # Create instance with appropriate settings
            try:
                response = lightsail.create_instances(
                    instanceNames=[instance_name],
                    availabilityZone=f'{aws_region}a',
                    blueprintId=blueprint_id,
                    bundleId=bundle_id,
                    tags=[
                        {'key': 'Application', 'value': app_name},
                        {'key': 'ManagedBy', 'value': 'GitHub-Actions'},
                        {'key': 'Type', 'value': app_type}
                    ]
                )
                print(f"✅ Instance creation initiated with {bundle_id}")
                
                # Wait for instance to be running
                print("⏳ Waiting for instance to be running...")
                max_wait = 300  # 5 minutes
                wait_interval = 10
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(wait_interval)
                    elapsed += wait_interval
                    
                    try:
                        response = lightsail.get_instance(instanceName=instance_name)
                        instance = response['instance']
                        state = instance['state']['name']
                        print(f"   Instance state: {state} ({elapsed}s elapsed)")
                        
                        if state == 'running':
                            if 'publicIpAddress' in instance:
                                static_ip = instance['publicIpAddress']
                                print(f"✅ New instance is running with IP: {static_ip}")
                                break
                    except Exception as e:
                        print(f"   Waiting... {e}")
                
                if not static_ip:
                    print("❌ Instance did not get a public IP within timeout")
                    sys.exit(1)
                    
                # Open firewall ports for new instance
                print("\n🔥 Configuring firewall for new instance...")
                
                # Get custom ports from config
                firewall_config = config.get('dependencies', {}).get('firewall', {}).get('config', {})
                allowed_ports = firewall_config.get('allowed_ports', ['22', '80', '443'])
                
                # Convert to port info format
                port_infos = []
                for port in allowed_ports:
                    port_num = int(str(port).strip())
                    port_infos.append({'fromPort': port_num, 'toPort': port_num, 'protocol': 'tcp'})
                
                print(f"   Opening ports: {', '.join(map(str, allowed_ports))}")
                
                lightsail.put_instance_public_ports(
                    portInfos=port_infos,
                    instanceName=instance_name
                )
                print(f"✅ Firewall configured: {', '.join(map(str, allowed_ports))}")
                
                # Detect OS type from the blueprint we just created
                print(f"\n🔍 Detecting OS type from blueprint: {blueprint_id}")
                
                # Use OSDetector for OS detection
                detector = OSDetector()
                os_type, os_info = detector.detect_os_from_blueprint(blueprint_id)
                package_manager = os_info['package_manager']
                print(f"✅ {os_type.title()} OS detected from blueprint: {blueprint_id}")
                print(f"🔧 Package manager: {package_manager}")
                
                # Setup Lightsail bucket for new instance if configured
                bucket_config = config.get('lightsail', {}).get('bucket', {})
                if bucket_config.get('enabled', False):
                    bucket_name = bucket_config.get('name', '')
                    if bucket_name:
                        print(f"\n🪣 Setting up Lightsail bucket for new instance...")
                        try:
                            sys.path.insert(0, 'workflows')
                            from lightsail_bucket import LightsailBucket
                            
                            bucket_manager = LightsailBucket(region=aws_region)
                            access_level = bucket_config.get('access_level', 'read_only')
                            bundle_id_bucket = bucket_config.get('bundle_id', 'small_1_0')
                            
                            success, message = bucket_manager.setup_bucket_for_instance(
                                bucket_name=bucket_name,
                                instance_name=instance_name,
                                access_level=access_level,
                                bundle_id=bundle_id_bucket,
                                create_if_missing=True
                            )
                            
                            if success:
                                print(f"✅ {message}")
                            else:
                                print(f"⚠️  {message}")
                        except ImportError:
                            print("⚠️  Bucket configuration requested but lightsail_bucket module not available")
                    else:
                        print("⚠️  Bucket enabled but no name specified")
                else:
                    print("\nℹ️  Lightsail bucket not configured")
                
            except Exception as create_error:
                # Check if the error is because instance already exists
                error_message = str(create_error)
                if 'already exists' in error_message.lower() or 'duplicate' in error_message.lower():
                    print(f"⚠️  Instance '{instance_name}' already exists (race condition detected)")
                    print("   This can happen if the instance was created between our check and creation attempt")
                    print("   Attempting to use the existing instance...")
                    
                    # Try to get the existing instance
                    try:
                        response = lightsail.get_instance(instanceName=instance_name)
                        instance = response['instance']
                        if 'publicIpAddress' in instance:
                            static_ip = instance['publicIpAddress']
                            print(f"✅ Using existing instance with IP: {static_ip}")
                        else:
                            print("⚠️  Existing instance has no public IP")
                        
                        # Detect operating system from blueprint for existing instance
                        blueprint_id = instance.get('blueprintId', '')
                        blueprint_name = instance.get('blueprintName', '')
                        print(f"📋 Blueprint: {blueprint_name} ({blueprint_id})")
                        
                        # Use OSDetector for OS detection
                        detector = OSDetector()
                        os_type, os_info = detector.detect_os_from_blueprint(blueprint_id)
                        package_manager = os_info['package_manager']
                        print(f"✅ {os_type.title()} OS detected: {blueprint_name}")
                        print(f"🔧 Package manager: {package_manager}")
                        
                    except Exception as get_error:
                        print(f"❌ Could not retrieve existing instance: {get_error}")
                        sys.exit(1)
                else:
                    print(f"❌ Failed to create instance: {create_error}")
                    sys.exit(1)
        
        except Exception as e:
            print(f"❌ Unexpected error while checking/creating instance: {e}")
            sys.exit(1)
        
        # Get enabled dependencies
        enabled_deps = []
        for dep_name, dep_config in config.get('dependencies', {}).items():
            if isinstance(dep_config, dict) and dep_config.get('enabled', False):
                enabled_deps.append(dep_name)
        
        enabled_dependencies = ','.join(enabled_deps)
        
        # Check if testing is enabled
        skip_tests = os.environ.get('SKIP_TESTS', 'false').lower() == 'true'
        test_enabled = not skip_tests and config.get('github_actions', {}).get('jobs', {}).get('test', {}).get('enabled', True)
        
        print(f"\n✅ Static IP: {static_ip}")
        print(f"✅ Enabled Dependencies: {enabled_dependencies}")
        print(f"✅ Testing Enabled: {test_enabled}")
        
        # For reusable workflows, always deploy when called
        should_deploy = True
        print(f"🚀 Should Deploy: {should_deploy}")
        
        # Get verification port from config (default to 80 for web apps)
        verification_port = config.get('deployment', {}).get('steps', {}).get('verification', {}).get('port', 80)
        if verification_port == 80:
            # Also check monitoring config
            verification_port = config.get('monitoring', {}).get('health_check', {}).get('port', 80)
        
        # Get verification path from config (default to /)
        verification_endpoints = config.get('deployment', {}).get('steps', {}).get('verification', {}).get('endpoints_to_test', ['/'])
        verification_path = verification_endpoints[0] if verification_endpoints else '/'
        
        print(f"✅ Verification Port: {verification_port}")
        print(f"✅ Verification Path: {verification_path}")
        
        # Write to GitHub outputs
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"instance_name={instance_name}\n")
                f.write(f"static_ip={static_ip}\n")
                f.write(f"aws_region={aws_region}\n")
                f.write(f"app_name={app_name}\n")
                f.write(f"app_type={app_type}\n")
                f.write(f"app_version={app_version}\n")
                f.write(f"should_deploy={str(should_deploy).lower()}\n")
                f.write(f"enabled_dependencies={enabled_dependencies}\n")
                f.write(f"test_enabled={str(test_enabled).lower()}\n")
                f.write(f"os_type={os_type}\n")
                f.write(f"package_manager={package_manager}\n")
                f.write(f"verification_port={verification_port}\n")
                f.write(f"verification_path={verification_path}\n")
        
        print("✅ Instance setup completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during instance setup: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()