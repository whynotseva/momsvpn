
import asyncio
import os
import sys
from app.api.services.remnawave import remnawave_service

# Mock logger to avoid errors if not configured
import logging
logging.basicConfig(level=logging.INFO)

async def check_user_sub(username):
    print(f"--- Checking user {username} ---")
    user = await remnawave_service.get_user(username)
    if not user:
        print("User not found via get_user (using get_all_users logic)")
        return
    
    print(f"User found: {user['username']}")
    print(f"UUID: {user.get('_uuid')}")
    sub_url = user.get("subscription_url")
    print(f"Sub URL: {sub_url}")
    
    if sub_url:
        import httpx
        try:
            async with httpx.AsyncClient(verify=False) as client:
                print(f"Fetching Sub URL content...")
                resp = await client.get(sub_url)
                print(f"Status: {resp.status_code}")
                content = resp.text
                print(f"Raw Content Length: {len(content)}")
                print("--- Content Preview (First 1000 chars) ---")
                print(content[:1000])
                print("--- End Preview ---")
                
                if "hysteria2://" in content:
                    print("SUCCESS: 'hysteria2://' FOUND in raw content.")
                elif "hy2://" in content:
                    print("SUCCESS: 'hy2://' FOUND in raw content.")
                else:
                    print("WARNING: 'hysteria2://' NOT FOUND in raw content.")
                    
                # Check base64
                import base64
                try:
                    decoded = base64.b64decode(content).decode()
                    print("--- Decoded Base64 Preview ---")
                    print(decoded[:1000])
                    if "hysteria2://" in decoded:
                        print("SUCCESS: 'hysteria2://' FOUND in decoded content.")
                    elif "hy2://" in decoded:
                        print("SUCCESS: 'hy2://' FOUND in decoded content.")
                except:
                    print("Content is not pure Base64 or failed to decode.")

        except Exception as e:
            print(f"Error fetching sub url: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = "hisevaaa"
    
    asyncio.run(check_user_sub(username))
