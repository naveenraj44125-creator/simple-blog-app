#!/usr/bin/env python3
"""
View Command Log - Display commands executed on Lightsail instance

This script retrieves and displays the command log from the Lightsail instance.
The log file is located at /var/log/deployment-commands.log on the instance.

Usage:
    python3 workflows/view_command_log.py [--lines N] [--clear]
    
Examples:
    # View last 50 commands (default)
    python3 workflows/view_command_log.py
    
    # View last 100 commands
    python3 workflows/view_command_log.py --lines 100
    
    # Clear the command log
    python3 workflows/view_command_log.py --clear
"""

import os
import sys
import argparse
from lightsail_common import create_lightsail_client

def main():
    parser = argparse.ArgumentParser(description='View command log from Lightsail instance')
    parser.add_argument('--instance-name', 
                       default=os.environ.get('LIGHTSAIL_INSTANCE_NAME', 'lamp-stack-demo'),
                       help='Lightsail instance name')
    parser.add_argument('--region', 
                       default=os.environ.get('AWS_REGION', 'us-east-1'),
                       help='AWS region')
    parser.add_argument('--lines', type=int, default=50,
                       help='Number of recent log lines to display (default: 50)')
    parser.add_argument('--clear', action='store_true',
                       help='Clear the command log on the instance')
    
    args = parser.parse_args()
    
    print("📋 Command Log Viewer")
    print("=" * 50)
    print(f"Instance: {args.instance_name}")
    print(f"Region: {args.region}")
    print("=" * 50)
    
    # Create Lightsail client
    client = create_lightsail_client(args.instance_name, args.region)
    
    if args.clear:
        # Clear the command log
        success, message = client.clear_command_log()
        if success:
            print(f"✅ {message}")
        else:
            print(f"❌ Failed to clear log: {message}")
            sys.exit(1)
    else:
        # Retrieve and display the command log
        success, log_content = client.get_command_log(args.lines)
        
        if success:
            if log_content.strip():
                print(f"\n📋 Last {args.lines} Commands Executed on Instance:")
                print("─" * 80)
                
                # Parse and display log entries
                lines = log_content.strip().split('\n')
                for i, line in enumerate(lines, 1):
                    if line.strip():
                        # Format: [timestamp] COMMAND: actual_command
                        if '] COMMAND: ' in line:
                            timestamp_part, command_part = line.split('] COMMAND: ', 1)
                            timestamp = timestamp_part.replace('[', '')
                            command = command_part.replace(' | ', '\n    ')  # Restore newlines
                            
                            print(f"{i:3d}. [{timestamp}]")
                            print(f"     Command: {command}")
                            print()
                        else:
                            print(f"{i:3d}. {line}")
                            print()
                
                print("─" * 80)
                print(f"📊 Total commands shown: {len([l for l in lines if l.strip()])}")
                print(f"📁 Log file location: /var/log/deployment-commands.log")
                print(f"💡 Use --clear to clear the log file")
            else:
                print("📋 No commands found in log")
        else:
            print(f"❌ Failed to retrieve command log: {log_content}")
            sys.exit(1)

if __name__ == "__main__":
    main()