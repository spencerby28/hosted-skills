#!/usr/bin/env python3
"""
X List Export Tool

Exports X (Twitter) list members to JSON using browser authentication.

Usage:
    python export_list.py --discover                    # List available lists
    python export_list.py --list-id <ID> -o out.json   # Export specific list
    python export_list.py --list-name "Name" -o out.json  # Export by name
    
Requirements:
    - Chrome/Arc running with --remote-debugging-port=9222
    - Logged into X in that browser
    - pip install requests websocket-client
"""

import argparse
import sys
import json
from typing import Optional

def main():
    parser = argparse.ArgumentParser(
        description='Export X (Twitter) list members to JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check browser connection
    python export_list.py --check
    
    # Discover available lists
    python export_list.py --discover
    
    # Export by list ID
    python export_list.py --list-id 1876334018150678826 -o gauntlet.json
    
    # Export by list name (partial match)
    python export_list.py --list-name "Gauntlet" -o gauntlet.json
    
    # Use custom CDP port
    python export_list.py --cdp-url http://localhost:9223 --discover
        """
    )
    
    parser.add_argument('--cdp-url', default='http://localhost:9222',
                        help='Chrome DevTools Protocol URL (default: http://localhost:9222)')
    parser.add_argument('--check', action='store_true',
                        help='Check browser connection and auth status')
    parser.add_argument('--discover', action='store_true',
                        help='List available X lists')
    parser.add_argument('--list-id', '-l',
                        help='List ID to export')
    parser.add_argument('--list-name', '-n',
                        help='List name to export (partial match)')
    parser.add_argument('--output', '-o', default='list_export.json',
                        help='Output JSON file (default: list_export.json)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress progress output')
    
    args = parser.parse_args()
    
    # Import modules here to show clear errors if dependencies missing
    try:
        from browser_auth import check_browser_connection, extract_auth_from_browser
        from x_api import XListsAPI, export_list_to_json
    except ImportError as e:
        print(f"Error importing modules: {e}")
        print("Make sure you're running from the skill directory.")
        sys.exit(1)
    
    # Check connection first
    if args.check or not any([args.discover, args.list_id, args.list_name]):
        if not args.quiet:
            print(f"Checking browser connection at {args.cdp_url}...")
        
        status = check_browser_connection(args.cdp_url)
        
        if not status['connected']:
            print(f"✗ Cannot connect to browser: {status.get('error')}")
            print("\nTo start Chrome with debugging:")
            print("  macOS:   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222")
            print("  Windows: chrome.exe --remote-debugging-port=9222")
            print("  Linux:   google-chrome --remote-debugging-port=9222")
            sys.exit(1)
        
        print(f"✓ Connected to {status['browser']}")
        print(f"  {status['tabs']} tabs open")
        
        if status['x_tab_found']:
            print(f"  ✓ X tab found: {status['x_tab_url']}")
        else:
            print("  ⚠ No X tab found (will try to extract auth anyway)")
        
        if not args.discover and not args.list_id and not args.list_name:
            # Just checking, extract auth to verify
            try:
                auth = extract_auth_from_browser(args.cdp_url)
                print(f"  ✓ Auth extracted successfully")
                print(f"\nRun with --discover to see available lists")
            except Exception as e:
                print(f"  ✗ Auth extraction failed: {e}")
                print("\nMake sure you're logged into X in the browser.")
                sys.exit(1)
            return
    
    # Extract auth
    try:
        auth = extract_auth_from_browser(args.cdp_url)
    except Exception as e:
        print(f"Error extracting auth: {e}")
        sys.exit(1)
    
    api = XListsAPI(auth)
    
    # Discover lists
    if args.discover:
        if not args.quiet:
            print("\nFetching your lists...")
        
        lists = api.get_my_lists()
        
        # Separate owned vs subscribed
        owned = [l for l in lists if l.mode in ['Private', 'Public']]
        
        print(f"\nFound {len(lists)} lists:\n")
        
        for lst in lists:
            mode_icon = "🔒" if lst.mode == 'Private' else "🌐"
            print(f"  {mode_icon} {lst.name}")
            print(f"     ID: {lst.id}")
            print(f"     Members: {lst.member_count}")
            if lst.owner_handle:
                print(f"     Owner: @{lst.owner_handle}")
            print()
        
        print("To export a list:")
        print(f"  python export_list.py --list-id <ID> -o export.json")
        return
    
    # Find list to export
    list_id = args.list_id
    
    if args.list_name and not list_id:
        lists = api.get_my_lists()
        matches = [l for l in lists if args.list_name.lower() in l.name.lower()]
        
        if not matches:
            print(f"No list found matching '{args.list_name}'")
            print("Run with --discover to see available lists")
            sys.exit(1)
        
        if len(matches) > 1:
            print(f"Multiple lists match '{args.list_name}':")
            for lst in matches:
                print(f"  - {lst.name} (ID: {lst.id})")
            print("\nUse --list-id to specify which one.")
            sys.exit(1)
        
        list_id = matches[0].id
        if not args.quiet:
            print(f"Found list: {matches[0].name}")
    
    if not list_id:
        print("Please specify --list-id or --list-name")
        print("Run with --discover to see available lists")
        sys.exit(1)
    
    # Export the list
    if not args.quiet:
        print(f"\nExporting list {list_id}...")
    
    def progress(count, total):
        if not args.quiet:
            print(f"  Fetched {count} members...", end='\r')
    
    try:
        result = export_list_to_json(api, list_id, args.output, progress_callback=progress)
        
        if not args.quiet:
            print(f"\n✓ Exported {result['member_count']} members to {args.output}")
            print(f"  List: {result['list']['name']}")
    except Exception as e:
        print(f"\nError exporting: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
