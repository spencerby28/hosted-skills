"""
Browser authentication module for X Lists skill.
Connects to Chrome/Arc via CDP and extracts auth credentials.
"""

import json
import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class XAuth:
    """X authentication credentials extracted from browser."""
    auth_token: str
    csrf_token: str  # ct0 cookie
    bearer_token: str
    cookies: Dict[str, str]
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers for X API requests."""
        return {
            'authorization': self.bearer_token,
            'x-csrf-token': self.csrf_token,
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
            'content-type': 'application/json',
        }
    
    def get_cookie_string(self) -> str:
        """Get cookie header string."""
        return '; '.join(f'{k}={v}' for k, v in self.cookies.items())


def get_cdp_targets(cdp_url: str = 'http://localhost:9222') -> list:
    """Get available browser targets via CDP."""
    try:
        resp = requests.get(f'{cdp_url}/json/list', timeout=5)
        return resp.json()
    except requests.RequestException as e:
        raise ConnectionError(f"Cannot connect to browser at {cdp_url}. "
                            f"Make sure Chrome is running with --remote-debugging-port=9222") from e


def find_x_tab(cdp_url: str = 'http://localhost:9222') -> Optional[Dict[str, Any]]:
    """Find an X.com tab in the browser."""
    targets = get_cdp_targets(cdp_url)
    for target in targets:
        url = target.get('url', '')
        if 'x.com' in url or 'twitter.com' in url:
            return target
    return None


def extract_auth_from_browser(cdp_url: str = 'http://localhost:9222') -> XAuth:
    """
    Extract X authentication from browser via CDP.
    
    This uses Puppeteer-style CDP to get cookies and capture auth headers.
    """
    import websocket
    import json
    
    # Find X tab or any tab to get cookies
    targets = get_cdp_targets(cdp_url)
    target = None
    
    # Prefer X tab, fallback to any page
    for t in targets:
        if t.get('type') == 'page':
            url = t.get('url', '')
            if 'x.com' in url or 'twitter.com' in url:
                target = t
                break
    
    if not target:
        # Use first available page
        for t in targets:
            if t.get('type') == 'page':
                target = t
                break
    
    if not target:
        raise RuntimeError("No browser tabs found. Open X.com in the browser first.")
    
    # Connect via WebSocket to get cookies
    ws_url = target['webSocketDebuggerUrl']
    ws = websocket.create_connection(ws_url)
    
    try:
        # Get all cookies
        ws.send(json.dumps({
            'id': 1,
            'method': 'Network.getAllCookies'
        }))
        result = json.loads(ws.recv())
        
        cookies = {}
        for cookie in result.get('result', {}).get('cookies', []):
            if cookie.get('domain', '').endswith('x.com') or cookie.get('domain', '').endswith('twitter.com'):
                cookies[cookie['name']] = cookie['value']
        
        # Extract required tokens
        auth_token = cookies.get('auth_token')
        csrf_token = cookies.get('ct0')
        
        if not auth_token or not csrf_token:
            raise RuntimeError("Not logged into X. Please log in at x.com first.")
        
        # The bearer token is a constant for X's web app
        bearer_token = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
        
        return XAuth(
            auth_token=auth_token,
            csrf_token=csrf_token,
            bearer_token=bearer_token,
            cookies=cookies
        )
    finally:
        ws.close()


def check_browser_connection(cdp_url: str = 'http://localhost:9222') -> Dict[str, Any]:
    """Check browser connection and return status."""
    try:
        resp = requests.get(f'{cdp_url}/json/version', timeout=5)
        version_info = resp.json()
        targets = get_cdp_targets(cdp_url)
        x_tab = find_x_tab(cdp_url)
        
        return {
            'connected': True,
            'browser': version_info.get('Browser', 'Unknown'),
            'tabs': len([t for t in targets if t.get('type') == 'page']),
            'x_tab_found': x_tab is not None,
            'x_tab_url': x_tab.get('url') if x_tab else None
        }
    except Exception as e:
        return {
            'connected': False,
            'error': str(e)
        }


if __name__ == '__main__':
    import sys
    
    cdp_url = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:9222'
    
    print(f"Checking browser connection at {cdp_url}...")
    status = check_browser_connection(cdp_url)
    print(json.dumps(status, indent=2))
    
    if status['connected']:
        print("\nExtracting auth...")
        try:
            auth = extract_auth_from_browser(cdp_url)
            print(f"✓ Auth token: {auth.auth_token[:20]}...")
            print(f"✓ CSRF token: {auth.csrf_token[:20]}...")
            print(f"✓ Cookies: {len(auth.cookies)} total")
        except Exception as e:
            print(f"✗ Failed: {e}")
