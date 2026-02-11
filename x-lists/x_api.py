"""
X (Twitter) API wrapper for list operations.
Uses GraphQL endpoints with browser-extracted auth.
"""

import json
import requests
from typing import List, Dict, Any, Optional, Generator
from dataclasses import dataclass, asdict
from browser_auth import XAuth

# GraphQL endpoint IDs (these are hashed operation names, may change)
ENDPOINTS = {
    'ListMembers': '7FPk01hdc1jyzL6Gj8vMZw',
    'ListByRestId': 'Tzkkg-NaBi_y1aAUUb6_eQ',
    'ListsManagementPageTimeline': 'FHavhcMS-6NrywtPkWiOHg',
    'ListLatestTweetsTimeline': 'aJxgBm1YveGJCRiWJFx5WA',
}

# Feature flags required for requests
DEFAULT_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "profile_foundations_tweet_stats_enabled": True,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "responsive_web_home_pinned_timelines_enabled": True,
    "long_form_notetweets_consumption_enabled": True,
    "responsive_web_media_download_video_enabled": True,
}


@dataclass
class ListMember:
    """A member of an X list."""
    id: str
    handle: str
    name: str
    description: str
    followers_count: int
    following_count: int
    verified: bool
    profile_image_url: str
    created_at: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    
    @classmethod
    def from_api(cls, user_result: Dict[str, Any]) -> 'ListMember':
        """Create from API response user_results.result."""
        legacy = user_result.get('legacy', {})
        return cls(
            id=user_result.get('rest_id', ''),
            handle=legacy.get('screen_name', ''),
            name=legacy.get('name', ''),
            description=legacy.get('description', ''),
            followers_count=legacy.get('followers_count', 0),
            following_count=legacy.get('friends_count', 0),
            verified=user_result.get('is_blue_verified', False),
            profile_image_url=legacy.get('profile_image_url_https', ''),
            created_at=legacy.get('created_at'),
            location=legacy.get('location'),
            url=legacy.get('url')
        )


@dataclass
class XList:
    """An X list."""
    id: str
    name: str
    description: str
    member_count: int
    subscriber_count: int
    mode: str  # 'Public' or 'Private'
    created_at: int  # Unix timestamp in ms
    owner_handle: Optional[str] = None
    owner_name: Optional[str] = None
    
    @classmethod
    def from_api(cls, list_data: Dict[str, Any]) -> 'XList':
        """Create from API response list object."""
        owner = list_data.get('user_results', {}).get('result', {})
        owner_legacy = owner.get('legacy', owner.get('core', {}))
        
        return cls(
            id=list_data.get('id_str', ''),
            name=list_data.get('name', ''),
            description=list_data.get('description', ''),
            member_count=list_data.get('member_count', 0),
            subscriber_count=list_data.get('subscriber_count', 0),
            mode=list_data.get('mode', 'Public'),
            created_at=list_data.get('created_at', 0),
            owner_handle=owner_legacy.get('screen_name'),
            owner_name=owner_legacy.get('name')
        )


class XListsAPI:
    """API client for X list operations."""
    
    BASE_URL = 'https://x.com/i/api/graphql'
    
    def __init__(self, auth: XAuth):
        self.auth = auth
        self.session = requests.Session()
        self.session.headers.update(self.auth.get_headers())
        self.session.headers['cookie'] = self.auth.get_cookie_string()
    
    def _graphql_request(self, endpoint_name: str, variables: Dict[str, Any], 
                         features: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        """Make a GraphQL request."""
        endpoint_id = ENDPOINTS.get(endpoint_name)
        if not endpoint_id:
            raise ValueError(f"Unknown endpoint: {endpoint_name}")
        
        url = f"{self.BASE_URL}/{endpoint_id}/{endpoint_name}"
        
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(features or DEFAULT_FEATURES)
        }
        
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    
    def get_my_lists(self) -> List[XList]:
        """Get all lists for the authenticated user."""
        data = self._graphql_request('ListsManagementPageTimeline', {'count': 100})
        
        lists = []
        instructions = data.get('data', {}).get('viewer', {}).get(
            'list_management_timeline', {}).get('timeline', {}).get('instructions', [])
        
        for inst in instructions:
            for entry in inst.get('entries', []):
                # Handle module items (suggestions)
                if entry.get('content', {}).get('items'):
                    for item in entry['content']['items']:
                        list_data = item.get('item', {}).get('itemContent', {}).get('list')
                        if list_data:
                            lists.append(XList.from_api(list_data))
                
                # Handle direct list entries (owned lists)
                list_data = entry.get('content', {}).get('itemContent', {}).get('list')
                if list_data:
                    lists.append(XList.from_api(list_data))
        
        return lists
    
    def get_list_info(self, list_id: str) -> XList:
        """Get info about a specific list."""
        data = self._graphql_request('ListByRestId', {'listId': list_id})
        list_data = data.get('data', {}).get('list', {})
        return XList.from_api(list_data)
    
    def get_list_members(self, list_id: str, count: int = 20, 
                         cursor: Optional[str] = None) -> tuple[List[ListMember], Optional[str]]:
        """
        Get members of a list (single page).
        
        Returns (members, next_cursor) where next_cursor is None if no more pages.
        """
        variables = {'listId': list_id, 'count': count}
        if cursor:
            variables['cursor'] = cursor
        
        data = self._graphql_request('ListMembers', variables)
        
        members = []
        next_cursor = None
        
        instructions = data.get('data', {}).get('list', {}).get(
            'members_timeline', {}).get('timeline', {}).get('instructions', [])
        
        for inst in instructions:
            for entry in inst.get('entries', []):
                # User entries
                user_result = entry.get('content', {}).get('itemContent', {}).get('user_results', {}).get('result')
                if user_result and user_result.get('legacy'):
                    members.append(ListMember.from_api(user_result))
                
                # Cursor entries
                if entry.get('content', {}).get('cursorType') == 'Bottom':
                    next_cursor = entry['content'].get('value')
        
        return members, next_cursor
    
    def get_all_list_members(self, list_id: str, 
                             progress_callback: Optional[callable] = None) -> Generator[ListMember, None, None]:
        """
        Generator that yields all members of a list, handling pagination.
        
        Args:
            list_id: The list ID
            progress_callback: Optional callback(fetched_count, total_estimated)
        """
        cursor = None
        fetched = 0
        
        while True:
            members, next_cursor = self.get_list_members(list_id, cursor=cursor)
            
            for member in members:
                yield member
                fetched += 1
            
            if progress_callback:
                progress_callback(fetched, None)
            
            if not next_cursor or not members:
                break
            
            cursor = next_cursor


def export_list_to_json(api: XListsAPI, list_id: str, output_path: str,
                        progress_callback: Optional[callable] = None) -> Dict[str, Any]:
    """
    Export a list to JSON file.
    
    Returns the export data dict.
    """
    from datetime import datetime
    
    # Get list info
    list_info = api.get_list_info(list_id)
    
    # Get all members
    members = list(api.get_all_list_members(list_id, progress_callback))
    
    export_data = {
        'list': asdict(list_info),
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'member_count': len(members),
        'members': [asdict(m) for m in members]
    }
    
    with open(output_path, 'w') as f:
        json.dump(export_data, f, indent=2)
    
    return export_data


if __name__ == '__main__':
    # Quick test
    from browser_auth import extract_auth_from_browser
    
    print("Connecting to browser...")
    auth = extract_auth_from_browser()
    api = XListsAPI(auth)
    
    print("\nYour lists:")
    for lst in api.get_my_lists():
        print(f"  - {lst.name} ({lst.member_count} members, {lst.mode})")
