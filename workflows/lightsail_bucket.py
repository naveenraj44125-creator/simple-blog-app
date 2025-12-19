#!/usr/bin/env python3
"""
Lightsail Bucket Management Module

This module handles Lightsail bucket operations including:
- Creating buckets if they don't exist
- Attaching buckets to instances with appropriate access levels
- Managing bucket access permissions
"""

import boto3
import time
from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError


class LightsailBucket:
    """Manages Lightsail bucket operations"""
    
    def __init__(self, region: str = 'us-east-1'):
        """
        Initialize Lightsail bucket manager
        
        Args:
            region: AWS region for Lightsail operations
        """
        self.region = region
        self.client = boto3.client('lightsail', region_name=region)
    
    def bucket_exists(self, bucket_name: str) -> bool:
        """
        Check if a Lightsail bucket exists
        
        Args:
            bucket_name: Name of the bucket to check
            
        Returns:
            True if bucket exists, False otherwise
        """
        try:
            self.client.get_buckets(bucketName=bucket_name)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NotFoundException':
                return False
            raise
    
    def create_bucket(
        self,
        bucket_name: str,
        bundle_id: str = 'small_1_0',
        tags: Optional[Dict[str, str]] = None
    ) -> Dict:
        """
        Create a new Lightsail bucket
        
        Args:
            bucket_name: Name for the new bucket
            bundle_id: Bundle ID for bucket size (small_1_0, medium_1_0, large_1_0)
            tags: Optional tags to apply to the bucket
            
        Returns:
            Dictionary with bucket information
        """
        print(f"📦 Creating Lightsail bucket: {bucket_name}")
        print(f"   Bundle: {bundle_id}")
        
        try:
            params = {
                'bucketName': bucket_name,
                'bundleId': bundle_id
            }
            
            if tags:
                params['tags'] = [
                    {'key': k, 'value': v} for k, v in tags.items()
                ]
            
            response = self.client.create_bucket(**params)
            
            # Wait for bucket to be active
            print("   Waiting for bucket to be active...")
            max_wait = 60  # 1 minute
            wait_interval = 5
            elapsed = 0
            
            while elapsed < max_wait:
                time.sleep(wait_interval)
                elapsed += wait_interval
                
                bucket_info = self.get_bucket_info(bucket_name)
                if bucket_info and bucket_info.get('state', {}).get('name') == 'OK':
                    print(f"✅ Bucket created successfully")
                    return bucket_info
                
                print(f"   Still creating... ({elapsed}s)")
            
            print("⚠️  Bucket creation timeout, but may still be in progress")
            return response.get('bucket', {})
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidInputException':
                print(f"❌ Invalid bucket name or bundle ID")
            raise
    
    def get_bucket_info(self, bucket_name: str) -> Optional[Dict]:
        """
        Get information about a Lightsail bucket
        
        Args:
            bucket_name: Name of the bucket
            
        Returns:
            Dictionary with bucket information or None if not found
        """
        try:
            response = self.client.get_buckets(bucketName=bucket_name)
            buckets = response.get('buckets', [])
            return buckets[0] if buckets else None
        except ClientError as e:
            if e.response['Error']['Code'] == 'NotFoundException':
                return None
            raise
    
    def set_instance_access(
        self,
        bucket_name: str,
        instance_name: str,
        access_level: str = 'read_only'
    ) -> bool:
        """
        Grant an instance access to a bucket
        
        Args:
            bucket_name: Name of the bucket
            instance_name: Name of the Lightsail instance
            access_level: Access level ('read_only' or 'read_write')
            
        Returns:
            True if successful, False otherwise
        """
        print(f"🔗 Attaching bucket to instance...")
        print(f"   Bucket: {bucket_name}")
        print(f"   Instance: {instance_name}")
        print(f"   Access: {access_level}")
        
        try:
            # Map access level to Lightsail API format
            access_map = {
                'read_only': 'read-only',
                'read_write': 'read-write',
                'read-only': 'read-only',
                'read-write': 'read-write'
            }
            
            api_access_level = access_map.get(access_level, 'read-only')
            
            response = self.client.set_resource_access_for_bucket(
                resourceName=instance_name,
                bucketName=bucket_name,
                access=api_access_level
            )
            
            print(f"✅ Instance access configured")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            
            if error_code == 'NotFoundException':
                print(f"❌ Bucket or instance not found")
            elif error_code == 'InvalidInputException':
                print(f"❌ Invalid access level: {access_level}")
            else:
                print(f"❌ Error setting access: {error_msg}")
            
            return False
    
    def get_bucket_access_keys(self, bucket_name: str) -> Optional[Dict]:
        """
        Get access keys for a bucket
        
        Args:
            bucket_name: Name of the bucket
            
        Returns:
            Dictionary with access key information or None
        """
        try:
            response = self.client.get_bucket_access_keys(bucketName=bucket_name)
            return response.get('accessKeys', [])
        except ClientError:
            return None
    
    def setup_bucket_for_instance(
        self,
        bucket_name: str,
        instance_name: str,
        access_level: str = 'read_only',
        bundle_id: str = 'small_1_0',
        create_if_missing: bool = True
    ) -> Tuple[bool, str]:
        """
        Complete bucket setup for an instance
        
        This method:
        1. Checks if bucket exists
        2. Creates bucket if it doesn't exist (and create_if_missing is True)
        3. Attaches bucket to instance with specified access level
        
        Args:
            bucket_name: Name of the bucket
            instance_name: Name of the Lightsail instance
            access_level: Access level ('read_only' or 'read_write')
            bundle_id: Bundle ID if creating new bucket
            create_if_missing: Whether to create bucket if it doesn't exist
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        print(f"\n{'='*60}")
        print(f"🪣 Setting up Lightsail Bucket")
        print(f"{'='*60}")
        
        # Check if bucket exists
        if self.bucket_exists(bucket_name):
            print(f"✅ Bucket already exists: {bucket_name}")
            bucket_info = self.get_bucket_info(bucket_name)
            
            if bucket_info:
                state = bucket_info.get('state', {}).get('name', 'UNKNOWN')
                url = bucket_info.get('url', 'N/A')
                print(f"   State: {state}")
                print(f"   URL: {url}")
        else:
            if not create_if_missing:
                return False, f"Bucket {bucket_name} does not exist and create_if_missing is False"
            
            print(f"📦 Bucket does not exist, creating...")
            
            try:
                tags = {
                    'ManagedBy': 'GitHub-Actions',
                    'Instance': instance_name
                }
                
                bucket_info = self.create_bucket(
                    bucket_name=bucket_name,
                    bundle_id=bundle_id,
                    tags=tags
                )
                
                if not bucket_info:
                    return False, "Failed to create bucket"
                    
            except Exception as e:
                return False, f"Error creating bucket: {str(e)}"
        
        # Attach bucket to instance
        print()
        success = self.set_instance_access(
            bucket_name=bucket_name,
            instance_name=instance_name,
            access_level=access_level
        )
        
        if not success:
            return False, "Failed to attach bucket to instance"
        
        # Get bucket info for summary
        bucket_info = self.get_bucket_info(bucket_name)
        if bucket_info:
            url = bucket_info.get('url', 'N/A')
            region = bucket_info.get('location', {}).get('regionName', self.region)
            
            print(f"\n{'='*60}")
            print(f"✅ Bucket Setup Complete")
            print(f"{'='*60}")
            print(f"Bucket Name: {bucket_name}")
            print(f"Bucket URL: {url}")
            print(f"Region: {region}")
            print(f"Access Level: {access_level}")
            print(f"Instance: {instance_name}")
            print(f"{'='*60}\n")
            
            return True, f"Bucket {bucket_name} configured successfully"
        
        return True, "Bucket attached but could not retrieve details"


def main():
    """Example usage"""
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python lightsail_bucket.py <bucket_name> <instance_name> [access_level] [bundle_id]")
        print("\nExample:")
        print("  python lightsail_bucket.py my-app-bucket my-instance read_write small_1_0")
        sys.exit(1)
    
    bucket_name = sys.argv[1]
    instance_name = sys.argv[2]
    access_level = sys.argv[3] if len(sys.argv) > 3 else 'read_only'
    bundle_id = sys.argv[4] if len(sys.argv) > 4 else 'small_1_0'
    
    bucket_manager = LightsailBucket()
    
    success, message = bucket_manager.setup_bucket_for_instance(
        bucket_name=bucket_name,
        instance_name=instance_name,
        access_level=access_level,
        bundle_id=bundle_id
    )
    
    if success:
        print(f"✅ {message}")
        sys.exit(0)
    else:
        print(f"❌ {message}")
        sys.exit(1)


if __name__ == '__main__':
    main()
