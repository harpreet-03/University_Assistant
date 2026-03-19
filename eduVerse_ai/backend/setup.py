#!/usr/bin/env python3
"""
setup.py — Initial Setup for EduVerse AI

Creates database tables and default admin account.

Usage:
    python setup.py
"""

import os
import sys
import secrets

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

import users
import auth


def main():
    print("="*60)
    print("EduVerse AI - Initial Setup")
    print("="*60)
    print()
    
    # Initialize database tables
    print("1. Creating database tables...")
    users.init_users_table()
    print("   ✓ Users table created")
    print("   ✓ Audit log table created")
    print()
    
    # Check if admin already exists
    existing_admin = users.list_users(role="admin")
    if existing_admin:
        print("⚠️  Admin account already exists:")
        for admin in existing_admin:
            print(f"   - {admin['username']} ({admin['full_name'] or 'No name'})")
        print()
        print("Setup complete. Use existing admin credentials to log in.")
        return
    
    # Create default admin
    print("2. Creating default admin account...")
    
    username = "admin"
    temp_password = secrets.token_urlsafe(12)[:16]  # 16-char random password
    
    try:
        user = users.create_user(
            username=username,
            password=temp_password,
            role="admin",
            full_name="System Administrator",
            email="admin@eduverse.local"
        )
        
        print("   ✓ Admin account created successfully!")
        print()
        print("="*60)
        print("IMPORTANT: Save these credentials!")
        print("="*60)
        print(f"Username: {username}")
        print(f"Password: {temp_password}")
        print("="*60)
        print()
        print("⚠️  You MUST change this password after first login!")
        print()
        print("Next steps:")
        print("1. Start the server: uvicorn main:app --reload --port 8000")
        print("2. Open http://localhost:8000")
        print("3. Click 'Sign In' and use the credentials above")
        print("4. Change your password immediately")
        print()
        
    except ValueError as e:
        print(f"   ✗ Error creating admin: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()