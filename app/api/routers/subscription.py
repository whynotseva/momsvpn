"""
Subscription Proxy Router.
Intercepts subscription requests from VPN clients (Happ), 
logs device info, and proxies to Marzban.
"""
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
import httpx
import logging
import re
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sub", tags=["subscription"])

MARZBAN_URL = os.getenv("MARZBAN_URL", "https://instabotwebhook.ru:8000")


def parse_device_from_headers(headers: dict) -> dict:
    """Parse device info from HTTP headers."""
    user_agent = headers.get("user-agent", "")
    
    device_info = {
        "user_agent": user_agent,
        "device_name": None,
        "os_version": None,
        "app_name": None,
        "app_version": None
    }
    
    if not user_agent:
        return device_info
    
    ua_lower = user_agent.lower()
    
    # Parse Happ: "Happ/3.7.0/ios CFNetwork/3860.300.31 Darwin/25.2.0"
    # Or other clients
    
    # Extract app name and version
    app_match = re.match(r'^(\w+)/([0-9.]+)', user_agent)
    if app_match:
        device_info["app_name"] = app_match.group(1)
        device_info["app_version"] = app_match.group(2)
    
    # Darwin version to iOS version mapping (approximate)
    darwin_to_ios = {
        "25.": "18.",  # iOS 18.x
        "24.": "17.",  # iOS 17.x
        "23.": "16.",  # iOS 16.x
        "22.": "15.",  # iOS 15.x
        "21.": "14.",  # iOS 14.x
    }
    
    darwin_match = re.search(r'darwin/(\d+)\.(\d+)', ua_lower)
    if darwin_match:
        major = darwin_match.group(1)
        minor = darwin_match.group(2)
        for darwin_prefix, ios_prefix in darwin_to_ios.items():
            if major + "." == darwin_prefix:
                # Convert Darwin minor to approximate iOS minor
                ios_minor = int(minor) // 100 if int(minor) > 10 else minor
                device_info["os_version"] = f"iOS {ios_prefix}{ios_minor}"
                break
    
    # Detect device type
    if "iphone" in ua_lower or "/ios" in ua_lower:
        device_info["device_name"] = "iPhone"
    elif "ipad" in ua_lower:
        device_info["device_name"] = "iPad"
    elif "android" in ua_lower:
        device_info["device_name"] = "Android"
        # Try to extract Android version
        android_match = re.search(r'android[/\s]*([\d.]+)', ua_lower)
        if android_match:
            device_info["os_version"] = f"Android {android_match.group(1)}"
    elif "windows" in ua_lower:
        device_info["device_name"] = "Windows PC"
        device_info["os_version"] = "Windows"
    elif "mac" in ua_lower:
        device_info["device_name"] = "Mac"
        device_info["os_version"] = "macOS"
    
    # Log full headers for debugging
    logger.info(f"Device parsed: {device_info}")
    
    return device_info


@router.get("/{token}")
async def subscription_proxy(token: str, request: Request):
    """
    Proxy subscription requests to Marzban while capturing device info.
    Adds Hysteria2 and Shadowsocks links for unified subscription.
    """
    import base64
    
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"
    
    # Parse device info from headers
    headers_dict = dict(request.headers)
    device_info = parse_device_from_headers(headers_dict)
    
    # Log for debugging
    logger.info(f"Subscription request for token: {token[:20]}...")
    logger.info(f"Client IP: {client_ip}")
    logger.info(f"User-Agent: {device_info['user_agent']}")
    logger.info(f"Parsed device: {device_info['device_name']} / {device_info['os_version']}")
    
    # Proxy request to Marzban
    try:
        async with httpx.AsyncClient(verify=os.getenv("MARZBAN_VERIFY_SSL", "true").lower() != "false", timeout=30) as client:
            marzban_url = f"{MARZBAN_URL}/sub/{token}"
            response = await client.get(marzban_url, headers={
                "User-Agent": headers_dict.get("user-agent", "")
            })
            
            if response.status_code != 200:
                return PlainTextResponse(content=response.text, status_code=response.status_code)
            
            # Get upstream links and decode from base64 if needed
            all_links = []
            upstream_content = response.text.strip()
            
            # DEBUG: Log raw content to see if Hysteria2 is present
            logger.info(f"Raw subscription content for {token[:10]}...: {upstream_content[:500]}...")
            
            for line in upstream_content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                # Check if it's already a plain link
                if line.startswith(('vless://', 'vmess://', 'trojan://', 'ss://', 'hysteria2://', 'hy2://')):
                    all_links.append(line)
                else:
                    # Try to decode base64
                    try:
                        decoded = base64.b64decode(line).decode('utf-8')
                        # Split if multiple links in one base64 block
                        for decoded_line in decoded.split('\n'):
                            decoded_line = decoded_line.strip()
                            if decoded_line.startswith(('vless://', 'vmess://', 'trojan://', 'ss://', 'hysteria2://', 'hy2://')):
                                all_links.append(decoded_line)
                    except Exception:
                        # If can't decode, skip
                        pass
            
            # Process and enhance links from Marzban
            enhanced_links = []
            user_uuid = None  # Will extract from VLESS links
            has_trojan = False  # Track if Trojan already in subscription
            profile_counter = 0
            
            for link in all_links:
                # Extract UUID from VLESS links for Trojan
                if link.startswith('vless://'):
                    uuid_match = link.split('://')[1].split('@')[0]
                    if uuid_match:
                        user_uuid = uuid_match
                
                # Track if Trojan already exists
                if link.startswith('trojan://'):
                    has_trojan = True
                
                # Rename profiles with MomsVPN branding
                if '#' in link:
                    base, old_name = link.rsplit('#', 1)
                    profile_counter += 1
                    
                    if 'security=reality' in link:
                        # Primary - Reality with fragmentation
                        link = f"{base}&fragment=3,1,tlshello#✅ Основной Moms"
                    elif link.startswith('vless://') and 'type=ws' in link:
                        link = f"{base}#✅ Запасной Moms"
                    elif link.startswith('trojan://'):
                        link = f"{base}#✅ Альтернативный Moms"
                    elif link.startswith('ss://'):
                        continue  # Skip, we add our own SS below
                else:
                    # Add fragment to Reality without name
                    if 'security=reality' in link:
                        link = f"{link}&fragment=3,1,tlshello#✅ Основной Moms"
                
                enhanced_links.append(link)
            
            # Add Trojan WebSocket as fallback only if not already present
            if user_uuid and not has_trojan:
                trojan_link = f"trojan://{user_uuid}@instabotwebhook.ru:443?security=tls&type=ws&path=%2Ftrojanws&sni=instabotwebhook.ru&fp=chrome#✅ Альтернативный Moms"
                enhanced_links.append(trojan_link)
            
            # Add Shadowsocks as last resort
            ss_key = "6Xtl5eyOFNZ73i0xfHWeCw=="
            ss_userinfo = base64.b64encode(f"2022-blake3-aes-128-gcm:{ss_key}".encode()).decode()
            shadowsocks_link = f"ss://{ss_userinfo}@31.130.130.238:8388#✅ Резервный Moms"
            enhanced_links.append(shadowsocks_link)
            
            # Return all links, newline separated
            content = "\n".join(enhanced_links)
            
            # Forward ALL Marzban headers for traffic display and branding
            response_headers = {
                "Content-Type": "text/plain; charset=utf-8",
            }
            
            # Forward Marzban headers exactly as-is (preserves traffic, name, etc)
            headers_to_forward = [
                'subscription-userinfo',   # Traffic: upload, download, total, expire
                'profile-title',           # Subscription name (already base64 from Marzban)
                'profile-update-interval', # Update interval
                'support-url',             # Support link
                'profile-web-page-url',    # Web page
                'content-disposition',     # Filename
            ]
            
            for header_name in headers_to_forward:
                if header_name in response.headers:
                    response_headers[header_name] = response.headers[header_name]
            
            return PlainTextResponse(
                content=content,
                status_code=200,
                headers=response_headers
            )
    except Exception as e:
        logger.error(f"Error proxying to Marzban: {e}")
        return PlainTextResponse(content="Error", status_code=500)

