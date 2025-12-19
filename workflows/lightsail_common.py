#!/usr/bin/env python3
"""
Common utilities for AWS Lightsail deployment workflows
This module provides shared functionality for SSH connections, file operations, and AWS client management
"""

import boto3
import subprocess
import tempfile
import os
import time
import sys
import socket
from botocore.exceptions import ClientError, NoCredentialsError

class LightsailBase:
    """Base class for Lightsail operations with common SSH and AWS functionality"""
    
    def __init__(self, instance_name, region='us-east-1'):
        self.instance_name = instance_name
        self.region = region
        try:
            self.lightsail = boto3.client('lightsail', region_name=region)
        except NoCredentialsError:
            print("❌ AWS credentials not found. Please configure AWS credentials.")
            sys.exit(1)
    
    def run_command(self, command, timeout=300, max_retries=1, show_output_lines=20, verbose=False):
        """
        Execute command on Lightsail instance using get_instance_access_details
        
        Args:
            command (str): Command to execute
            timeout (int): Command timeout in seconds
            max_retries (int): Maximum number of retry attempts
            show_output_lines (int): Number of output lines to display
            verbose (bool): Show detailed command execution
            
        Returns:
            tuple: (success: bool, output: str)
        """
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"🔄 Retry attempt {attempt + 1}/{max_retries}")
                    # Optimized backoff for GitHub Actions - shorter waits for faster deployment
                    if "GITHUB_ACTIONS" in os.environ:
                        wait_time = min(5 + (attempt * 5), 20)  # Faster retries in CI
                    else:
                        wait_time = min(15 + (attempt * 10), 60)  # Original timing for local
                    print(f"   ⏳ Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    
                    # Test connectivity before retry
                    if not self.test_network_connectivity():
                        print("   ⚠️ Network connectivity still failing, continuing retry...")
                
                # Get SSH access details first
                ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
                ssh_details = ssh_response['accessDetails']
                
                # Show EXACT command being sent to host
                print(f"📡 Sending command to {ssh_details['username']}@{ssh_details['ipAddress']}:")
                print("─" * 80)
                print("COMMAND START:")
                
                # Format command display for better readability
                if '\n' in command and len(command.split('\n')) > 3:
                    # Multi-line command - show it formatted
                    lines = command.split('\n')
                    for i, line in enumerate(lines, 1):
                        if line.strip():
                            print(f"{i:2d}: {line}")
                        else:
                            print(f"{i:2d}:")
                else:
                    # Single line or short command
                    print(command)
                
                print("COMMAND END:")
                print("─" * 80)
                
                # Log command to file on the instance
                self._log_command_to_instance(ssh_details, command)
                
                # Create temporary SSH key files
                key_path, cert_path = self.create_ssh_files(ssh_details)
                
                try:
                    ssh_cmd = self._build_ssh_command(key_path, cert_path, ssh_details, command)
                    
                    # Show full SSH command being executed
                    if "GITHUB_ACTIONS" in os.environ:
                        print(f"🔧 Full SSH Command:")
                        ssh_cmd_str = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in ssh_cmd])
                        print(f"   {ssh_cmd_str}")
                        print("─" * 80)
                    
                    print(f"⏳ Executing on remote host...")
                    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
                    
                    print("─" * 80)
                    print("REMOTE HOST OUTPUT:")
                    print("─" * 80)
                    
                    if result.returncode == 0:
                        print(f"✅ SUCCESS (exit code: 0)")
                        if result.stdout.strip():
                            print("STDOUT:")
                            print(result.stdout)
                        if result.stderr.strip():
                            print("STDERR:")
                            print(result.stderr)
                        print("─" * 80)
                        return True, result.stdout.strip()
                    else:
                        print(f"❌ FAILED (exit code: {result.returncode})")
                        if result.stdout.strip():
                            print("STDOUT:")
                            print(result.stdout)
                        if result.stderr.strip():
                            print("STDERR:")
                            print(result.stderr)
                        print("─" * 80)
                        return False, result.stderr.strip()
                        
                        # Check if it's a connection issue that we should retry
                        if max_retries > 1 and self._is_connection_error(error_msg):
                            if attempt < max_retries - 1:
                                print(f"   🔄 Connection issue detected, will retry...")
                                # For GitHub Actions, try to restart instance on persistent failures
                                if attempt >= 3 and "GITHUB_ACTIONS" in os.environ:
                                    print("   🔄 GitHub Actions detected - attempting instance restart...")
                                    self.restart_instance_for_connectivity()
                                continue
                        
                        return False, error_msg
                    
                finally:
                    self._cleanup_ssh_files(key_path, cert_path)
                    
            except subprocess.TimeoutExpired:
                print(f"   ⏰ Command timed out after {timeout} seconds")
                if attempt < max_retries - 1:
                    print(f"   🔄 Will retry...")
                    continue
                return False, f"Command timed out after {timeout} seconds"
            except Exception as e:
                error_msg = str(e)
                print(f"   ❌ Error: {error_msg}")
                
                # Check if it's a connection issue that we should retry
                if max_retries > 1 and self._is_connection_error(error_msg):
                    if attempt < max_retries - 1:
                        print(f"   🔄 Connection issue detected, will retry...")
                        continue
                
                return False, error_msg
        
        return False, "Max retries exceeded"

    def create_ssh_files(self, ssh_details):
        """
        Create temporary SSH key files from Lightsail access details
        
        Args:
            ssh_details (dict): SSH access details from get_instance_access_details
            
        Returns:
            tuple: (key_path: str, cert_path: str)
        """
        # Create private key file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as key_file:
            key_file.write(ssh_details['privateKey'])
            key_path = key_file.name
        
        # Create certificate file
        cert_path = key_path + '-cert.pub'
        cert_parts = ssh_details['certKey'].split(' ', 2)
        formatted_cert = f'{cert_parts[0]} {cert_parts[1]}\n' if len(cert_parts) >= 2 else ssh_details['certKey'] + '\n'
        
        with open(cert_path, 'w') as cert_file:
            cert_file.write(formatted_cert)
        
        # Set proper permissions
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o600)
        
        return key_path, cert_path

    def copy_file_to_instance(self, local_path, remote_path, timeout=300):
        """
        Copy file to instance using SCP
        
        Args:
            local_path (str): Local file path
            remote_path (str): Remote file path
            timeout (int): Transfer timeout in seconds
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"📤 Copying {local_path} to {remote_path}")
            
            ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
            ssh_details = ssh_response['accessDetails']
            
            key_path, cert_path = self.create_ssh_files(ssh_details)
            
            try:
                scp_cmd = [
                    'scp', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=30', '-o', 'IdentitiesOnly=yes',
                    local_path, f'{ssh_details["username"]}@{ssh_details["ipAddress"]}:{remote_path}'
                ]
                
                result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=timeout)
                
                if result.returncode == 0:
                    print(f"   ✅ File copied successfully")
                    return True
                else:
                    print(f"   ❌ Failed to copy file (exit code: {result.returncode})")
                    if result.stderr.strip():
                        print(f"   Error: {result.stderr.strip()}")
                    return False
                
            finally:
                self._cleanup_ssh_files(key_path, cert_path)
                
        except Exception as e:
            print(f"   ❌ Error copying file: {str(e)}")
            return False

    def get_instance_info(self):
        """
        Get instance information including public IP and state
        
        Returns:
            dict: Instance information or None if error
        """
        try:
            response = self.lightsail.get_instance(instanceName=self.instance_name)
            instance = response['instance']
            return {
                'name': instance['name'],
                'state': instance['state']['name'],
                'public_ip': instance.get('publicIpAddress'),
                'private_ip': instance.get('privateIpAddress'),
                'blueprint': instance.get('blueprintName'),
                'bundle': instance.get('bundleId')
            }
        except ClientError as e:
            print(f"❌ Error getting instance info: {e}")
            return None

    def wait_for_instance_state(self, target_state='running', timeout=300):
        """
        Wait for instance to reach target state
        
        Args:
            target_state (str): Target instance state
            timeout (int): Maximum wait time in seconds
            
        Returns:
            bool: True if target state reached, False otherwise
        """
        print(f"⏳ Waiting for instance {self.instance_name} to be {target_state}...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = self.lightsail.get_instance(instanceName=self.instance_name)
                current_state = response['instance']['state']['name']
                print(f"Instance state: {current_state}")
                
                if current_state == target_state:
                    print(f"✅ Instance is {target_state}")
                    return True
                elif current_state in ['stopped', 'stopping', 'terminated'] and target_state == 'running':
                    print(f"❌ Instance is in {current_state} state")
                    return False
                    
                time.sleep(10)
            except ClientError as e:
                print(f"❌ Error checking instance state: {e}")
                return False
        
        print(f"❌ Timeout waiting for instance to be {target_state}")
        return False

    def test_ssh_connectivity(self, timeout=30, max_retries=3):
        """
        Test SSH connectivity to the instance with enhanced resilience
        
        Args:
            timeout (int): Connection timeout
            max_retries (int): Maximum retry attempts
            
        Returns:
            bool: True if SSH is accessible, False otherwise
        """
        print("🔍 Testing SSH connectivity...")
        
        # For GitHub Actions, use optimized retry strategy for faster deployments
        if "GITHUB_ACTIONS" in os.environ:
            print("   🤖 GitHub Actions detected - using optimized retry strategy")
            # Reduce retries and timeout for faster deployment in CI
            max_retries = min(max_retries, 3)  # Maximum 3 retries in CI
            timeout = min(timeout, 45)  # Maximum 45s timeout in CI
        
        success, _ = self.run_command("echo 'SSH test successful'", timeout=timeout, max_retries=max_retries)
        if success:
            print("✅ SSH connectivity confirmed")
        else:
            print("❌ SSH connectivity failed")
            
            # In GitHub Actions, try one more time with instance restart
            if "GITHUB_ACTIONS" in os.environ and not success:
                print("   🔄 GitHub Actions: Attempting instance restart as last resort...")
                if self.restart_instance_for_connectivity():
                    print("   🔄 Retrying SSH after restart...")
                    success, _ = self.run_command("echo 'SSH test after restart'", timeout=60, max_retries=2)
                    if success:
                        print("✅ SSH connectivity restored after restart")
                    else:
                        print("❌ SSH still failing after restart")
        
        return success

    def test_network_connectivity(self):
        """Test network connectivity to the instance"""
        try:
            ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
            ip_address = ssh_response['accessDetails']['ipAddress']
            
            print(f"🔍 Testing network connectivity to {ip_address}...")
            
            # Test basic connectivity
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            result = sock.connect_ex((ip_address, 22))
            sock.close()
            
            if result == 0:
                print("✅ Network connectivity to SSH port successful")
                return True
            else:
                print(f"⚠️ Network connectivity test failed (error code: {result})")
                return False
                
        except Exception as e:
            print(f"⚠️ Network connectivity test error: {e}")
            return False

    def restart_instance_for_connectivity(self):
        """Restart instance to resolve connectivity issues (GitHub Actions fallback)"""
        try:
            print("🔄 Attempting instance restart to resolve connectivity...")
            
            # Stop instance
            self.lightsail.stop_instance(instanceName=self.instance_name)
            print("   ⏳ Stopping instance...")
            time.sleep(30)
            
            # Wait for stopped state
            for _ in range(12):  # 2 minutes max
                response = self.lightsail.get_instance(instanceName=self.instance_name)
                state = response['instance']['state']['name']
                if state == 'stopped':
                    break
                time.sleep(10)
            
            # Start instance
            self.lightsail.start_instance(instanceName=self.instance_name)
            print("   ⏳ Starting instance...")
            time.sleep(60)
            
            # Wait for running state
            for _ in range(18):  # 3 minutes max
                response = self.lightsail.get_instance(instanceName=self.instance_name)
                state = response['instance']['state']['name']
                if state == 'running':
                    print("   ✅ Instance restarted successfully")
                    time.sleep(30)  # Additional wait for SSH service
                    return True
                time.sleep(10)
                
            print("   ⚠️ Instance restart timeout")
            return False
            
        except Exception as e:
            print(f"   ❌ Instance restart failed: {e}")
            return False

    def _build_ssh_command(self, key_path, cert_path, ssh_details, command):
        """Build SSH command with proper options and safe command encoding"""
        import base64
        
        # Encode the command to avoid shell parsing issues
        encoded_command = base64.b64encode(command.encode('utf-8')).decode('ascii')
        safe_command = f"echo '{encoded_command}' | base64 -d | bash"
        
        # Enhanced SSH configuration for GitHub Actions compatibility
        if "GITHUB_ACTIONS" in os.environ:
            return [
                'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=60', '-o', 'ServerAliveInterval=30',
                '-o', 'ServerAliveCountMax=6', '-o', 'ConnectionAttempts=3',
                '-o', 'IdentitiesOnly=yes', '-o', 'TCPKeepAlive=yes',
                '-o', 'ExitOnForwardFailure=yes', '-o', 'BatchMode=yes',
                '-o', 'PreferredAuthentications=publickey', '-o', 'LogLevel=VERBOSE',
                f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', safe_command
            ]
        else:
            return [
                'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=10',
                '-o', 'ServerAliveCountMax=3', '-o', 'IdentitiesOnly=yes',
                '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR',
                f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', safe_command
            ]

    def _display_output(self, output, max_lines):
        """Display command output with line limit"""
        lines = output.split('\n')
        for line in lines[:max_lines]:
            print(f"   {line}")
        if len(lines) > max_lines:
            print(f"   ... ({len(lines) - max_lines} more lines)")
    
    def _display_detailed_output(self, output, max_lines):
        """Display command output with detailed formatting for GitHub Actions"""
        lines = output.split('\n')
        for i, line in enumerate(lines[:max_lines], 1):
            if line.strip():
                print(f"   {i:3d}: {line}")
            else:
                print(f"   {i:3d}:")
        if len(lines) > max_lines:
            print(f"   ... ({len(lines) - max_lines} more lines truncated)")
    
    def run_command_with_live_output(self, command, timeout=300):
        """
        Execute command with live output streaming - shows each command as it executes
        """
        print(f"🔧 Executing with live output on {self.instance_name}:")
        
        # Break down complex scripts into individual commands
        if 'set -e' in command and '\n' in command:
            return self._run_script_with_individual_commands(command, timeout)
        else:
            return self.run_command(command, timeout, verbose=True)

    def _is_connection_error(self, error_msg):
        """Check if error message indicates a connection issue"""
        connection_errors = [
            'broken pipe', 'connection refused', 'connection timed out', 
            'network unreachable', 'host unreachable', 'no route to host',
            'connection reset', 'connection closed by remote host',
            'ssh_exchange_identification', 'connection lost', 'connection aborted',
            'operation timed out', 'connect to host', 'timed out after'
        ]
        return any(phrase in error_msg.lower() for phrase in connection_errors)

    def _log_command_to_instance(self, ssh_details, command):
        """Log command to a file on the Lightsail instance for tracking"""
        try:
            # Show that we're logging (only in GitHub Actions for visibility)
            if "GITHUB_ACTIONS" in os.environ:
                print(f"📝 Logging detailed commands to instance log file...")
            
            # Create log entry with timestamp
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            
            # For detailed logging, we want to log each individual command
            if '\n' in command:
                # Multi-line script - log each command separately
                lines = command.split('\n')
                
                # First, find script description for the header
                description = None
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped.startswith('echo ') and ('"' in line_stripped or "'" in line_stripped):
                        # Extract echo message
                        if line_stripped.startswith('echo "'):
                            description = line_stripped.replace('echo "', '').replace('"', '').strip()
                        elif line_stripped.startswith("echo '"):
                            description = line_stripped.replace("echo '", "").replace("'", "").strip()
                        else:
                            description = line_stripped.replace('echo ', '').strip()
                        
                        # Clean up common patterns
                        if description.startswith('✅') or description.startswith('🔧') or description.startswith('📦'):
                            description = description[2:].strip()
                        break
                
                if not description:
                    description = "Multi-line script"
                
                # Log script header
                script_header = f"[{timestamp}] SCRIPT_START: {description}"
                self._write_log_entry(ssh_details, script_header)
                
                # Log each individual command
                command_num = 1
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped and not line_stripped.startswith('#'):
                        if line_stripped != 'set -e':  # Skip error handling directive
                            individual_timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                            log_entry = f"[{individual_timestamp}] CMD_{command_num:02d}: {line_stripped}"
                            self._write_log_entry(ssh_details, log_entry)
                            command_num += 1
                
                # Log script end
                end_timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                script_end = f"[{end_timestamp}] SCRIPT_END: {description} (executed {command_num-1} commands)"
                self._write_log_entry(ssh_details, script_end)
                
            else:
                # Single line command
                log_entry = f"[{timestamp}] COMMAND: {command}"
                self._write_log_entry(ssh_details, log_entry)
                
        except Exception as e:
            # Show logging errors in GitHub Actions for debugging
            if "GITHUB_ACTIONS" in os.environ:
                print(f"   ⚠️ Logging exception: {str(e)}")
            pass

    def _write_log_entry(self, ssh_details, log_entry):
        """Write a single log entry to the instance log file"""
        try:
            # Escape single quotes in the log entry
            escaped_log_entry = log_entry.replace("'", "'\"'\"'")
            log_command = f"sudo mkdir -p /var/log && echo '{escaped_log_entry}' | sudo tee -a /var/log/deployment-commands.log > /dev/null"
            
            # Create temporary SSH key files for logging
            key_path, cert_path = self.create_ssh_files(ssh_details)
            
            try:
                # Build SSH command for logging
                ssh_cmd = [
                    'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR',
                    f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', log_command
                ]
                
                # Execute logging command
                result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
                
            finally:
                self._cleanup_ssh_files(key_path, cert_path)
                
        except Exception:
            pass  # Ignore individual logging errors

    def get_command_log(self, lines=50):
        """
        Retrieve the command log from the Lightsail instance
        
        Args:
            lines (int): Number of recent lines to retrieve
            
        Returns:
            tuple: (success: bool, log_content: str)
        """
        try:
            print(f"📋 Retrieving last {lines} commands from instance log...")
            
            # Get the log file content
            log_command = f"sudo tail -n {lines} /var/log/deployment-commands.log 2>/dev/null || echo 'No command log found'"
            success, output = self.run_command(log_command, timeout=30, max_retries=1)
            
            if success:
                if "No command log found" in output:
                    print("📋 No command log file found on instance")
                    return True, "No commands logged yet"
                else:
                    print(f"📋 Retrieved {len(output.split(chr(10)))} log entries")
                    return True, output
            else:
                print(f"❌ Failed to retrieve command log: {output}")
                return False, output
                
        except Exception as e:
            print(f"❌ Error retrieving command log: {e}")
            return False, str(e)

    def clear_command_log(self):
        """
        Clear the command log on the Lightsail instance
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            print("🧹 Clearing command log on instance...")
            
            # Clear the log file
            clear_command = "sudo rm -f /var/log/deployment-commands.log && echo 'Command log cleared'"
            success, output = self.run_command(clear_command, timeout=30, max_retries=1)
            
            if success:
                print("✅ Command log cleared successfully")
                return True, "Command log cleared"
            else:
                print(f"❌ Failed to clear command log: {output}")
                return False, output
                
        except Exception as e:
            print(f"❌ Error clearing command log: {e}")
            return False, str(e)

    def _cleanup_ssh_files(self, key_path, cert_path):
        """Clean up temporary SSH key files"""
        try:
            if os.path.exists(key_path):
                os.unlink(key_path)
            if os.path.exists(cert_path):
                os.unlink(cert_path)
        except Exception:
            pass  # Ignore cleanup errors
    
    def _run_script_with_individual_commands(self, script, timeout=300):
        """
        Run a bash script by executing individual commands and showing each one
        """
        print("📋 Breaking down script into individual commands:")
        
        # Parse the script into individual commands
        lines = script.split('\n')
        commands = []
        current_command = []
        in_heredoc = False
        heredoc_delimiter = None
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines and comments at the start
            if not stripped or stripped.startswith('#'):
                if current_command:  # Only add if we're building a command
                    current_command.append(line)
                continue
            
            # Skip 'set -e' as it's just error handling
            if stripped == 'set -e':
                continue
            
            # Handle heredoc start
            if '<<' in line and not in_heredoc:
                heredoc_delimiter = line.split('<<')[-1].strip().strip("'\"")
                current_command.append(line)
                in_heredoc = True
                continue
            
            # Handle heredoc end
            if in_heredoc:
                current_command.append(line)
                if stripped == heredoc_delimiter or stripped.endswith(heredoc_delimiter):
                    in_heredoc = False
                    heredoc_delimiter = None
                continue
            
            # Handle line continuations
            if line.endswith('\\'):
                current_command.append(line)
                continue
            
            # Add current line to command
            current_command.append(line)
            
            # If this looks like a complete command, save it
            if (stripped.endswith(';') or 
                not stripped.endswith('\\') and 
                not stripped.endswith('|') and
                not stripped.endswith('&&') and
                not stripped.endswith('||')):
                
                if current_command:
                    cmd_text = '\n'.join(current_command).strip()
                    if cmd_text and not cmd_text.startswith('#'):
                        commands.append(cmd_text)
                current_command = []
        
        # Add any remaining command
        if current_command:
            cmd_text = '\n'.join(current_command).strip()
            if cmd_text and not cmd_text.startswith('#'):
                commands.append(cmd_text)
        
        print(f"   📊 Found {len(commands)} individual commands to execute")
        
        # Execute each command individually
        all_output = []
        for i, cmd in enumerate(commands, 1):
            print(f"\n🔸 Step {i}/{len(commands)}: Executing individual command")
            
            # Show the command being executed
            cmd_lines = cmd.split('\n')
            print(f"📋 Command to execute:")
            for j, cmd_line in enumerate(cmd_lines):
                if cmd_line.strip():
                    print(f"   {j+1}: {cmd_line.strip()}")
            
            # Execute the command
            print(f"🚀 Sending to Lightsail host...")
            success, output = self.run_command(cmd, timeout=60, verbose=False)
            
            if success:
                print(f"      ✅ Command {i} completed successfully")
                if output.strip():
                    # Show key output lines
                    output_lines = output.split('\n')
                    for line in output_lines[:10]:  # Show first 10 lines
                        if line.strip():
                            print(f"         {line}")
                    if len(output_lines) > 10:
                        print(f"         ... ({len(output_lines)-10} more lines)")
                all_output.append(output)
            else:
                print(f"      ❌ Command {i} failed")
                if output:
                    print(f"         Error: {output}")
                return False, f"Command {i} failed: {output}"
        
        return True, '\n'.join(all_output)


class LightsailSSHManager(LightsailBase):
    """Enhanced SSH manager with additional connectivity features"""
    
    def wait_for_ssh_ready(self, timeout=300):
        """
        Wait for instance to be running and SSH to be ready
        
        Args:
            timeout (int): Maximum wait time in seconds
            
        Returns:
            bool: True if SSH is ready, False otherwise
        """
        # First wait for instance to be running
        if not self.wait_for_instance_state('running', timeout):
            return False
        
        # Wait additional time for SSH service to start
        print("⏳ Waiting for SSH service to be ready...")
        time.sleep(30)  # Give SSH service time to start
        
        # Test SSH connectivity with retries
        return self.test_ssh_connectivity(timeout=30, max_retries=3)


def create_lightsail_client(instance_name, region='us-east-1', client_type='base'):
    """
    Factory function to create appropriate Lightsail client
    
    Args:
        instance_name (str): Lightsail instance name
        region (str): AWS region
        client_type (str): Type of client ('base', 'ssh')
        
    Returns:
        LightsailBase or LightsailSSHManager: Configured client instance
    """
    if client_type == 'ssh':
        return LightsailSSHManager(instance_name, region)
    else:
        return LightsailBase(instance_name, region)
