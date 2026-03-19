import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

import users
import auth

def reset():
    username = "admin"
    new_password = "admin123"
    
    user = users.get_user(username)
    if not user:
        print(f"Error: User {username} not found.")
        return
    
    users.change_password(user["id"], new_password)
    print(f"Successfully reset password for {username} to: {new_password}")
    print("Please log in and change your password immediately.")

if __name__ == "__main__":
    reset()
