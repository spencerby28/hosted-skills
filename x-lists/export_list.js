#!/usr/bin/env node
/**
 * X List Export Tool (Node.js version)
 * 
 * Exports X (Twitter) list members to JSON using browser authentication.
 * 
 * Usage:
 *   node export_list.js --discover                    # List available lists
 *   node export_list.js --list-id <ID> -o out.json   # Export specific list
 *   node export_list.js --list-name "Name" -o out.json  # Export by name
 * 
 * Requirements:
 *   - Chrome/Arc running with --remote-debugging-port=9222
 *   - Logged into X in that browser
 *   - npm install puppeteer-core (already in /tmp)
 */

const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

// GraphQL endpoint IDs
const ENDPOINTS = {
  ListMembers: '7FPk01hdc1jyzL6Gj8vMZw',
  ListByRestId: 'Tzkkg-NaBi_y1aAUUb6_eQ',
  ListsManagementPageTimeline: 'FHavhcMS-6NrywtPkWiOHg',
};

// Feature flags required for requests (captured Feb 2026)
const DEFAULT_FEATURES = {
  rweb_video_screen_enabled: false,
  profile_label_improvements_pcf_label_in_post_enabled: true,
  responsive_web_profile_redirect_enabled: false,
  rweb_tipjar_consumption_enabled: false,
  verified_phone_label_enabled: false,
  creator_subscriptions_tweet_preview_api_enabled: true,
  responsive_web_graphql_timeline_navigation_enabled: true,
  responsive_web_graphql_skip_user_profile_image_extensions_enabled: false,
  premium_content_api_read_enabled: false,
  communities_web_enable_tweet_community_results_fetch: true,
  c9s_tweet_anatomy_moderator_badge_enabled: true,
  responsive_web_grok_analyze_button_fetch_trends_enabled: false,
  responsive_web_grok_analyze_post_followups_enabled: true,
  responsive_web_jetfuel_frame: true,
  responsive_web_grok_share_attachment_enabled: true,
  responsive_web_grok_annotations_enabled: true,
  articles_preview_enabled: true,
  responsive_web_edit_tweet_api_enabled: true,
  graphql_is_translatable_rweb_tweet_is_translatable_enabled: true,
  view_counts_everywhere_api_enabled: true,
  longform_notetweets_consumption_enabled: true,
  responsive_web_twitter_article_tweet_consumption_enabled: true,
  tweet_awards_web_tipping_enabled: false,
  responsive_web_grok_show_grok_translated_post: true,
  responsive_web_grok_analysis_button_from_backend: true,
  post_ctas_fetch_enabled: true,
  freedom_of_speech_not_reach_fetch_enabled: true,
  standardized_nudges_misinfo: true,
  tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled: true,
  longform_notetweets_rich_text_read_enabled: true,
  longform_notetweets_inline_media_enabled: true,
  responsive_web_grok_image_annotation_enabled: true,
  responsive_web_grok_imagine_annotation_enabled: true,
  responsive_web_grok_community_note_auto_translation_is_enabled: false,
  responsive_web_enhance_cards_enabled: false,
};

const BEARER_TOKEN = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA";

class XListsAPI {
  constructor(browser, page, cookies) {
    this.browser = browser;
    this.page = page;
    this.cookies = cookies;
    this.csrfToken = cookies.find(c => c.name === 'ct0')?.value;
    this.cookieString = cookies
      .filter(c => c.domain?.includes('x.com') || c.domain?.includes('twitter.com'))
      .map(c => `${c.name}=${c.value}`)
      .join('; ');
  }

  async graphqlRequest(endpointName, variables) {
    const endpointId = ENDPOINTS[endpointName];
    if (!endpointId) throw new Error(`Unknown endpoint: ${endpointName}`);

    const url = new URL(`https://x.com/i/api/graphql/${endpointId}/${endpointName}`);
    url.searchParams.set('variables', JSON.stringify(variables));
    url.searchParams.set('features', JSON.stringify(DEFAULT_FEATURES));

    const response = await this.page.evaluate(async (fetchUrl, csrfToken, bearer, cookieStr) => {
      const resp = await fetch(fetchUrl, {
        headers: {
          'authorization': bearer,
          'x-csrf-token': csrfToken,
          'x-twitter-auth-type': 'OAuth2Session',
          'x-twitter-active-user': 'yes',
          'content-type': 'application/json',
        },
        credentials: 'include'
      });
      return await resp.json();
    }, url.toString(), this.csrfToken, BEARER_TOKEN, this.cookieString);

    return response;
  }

  async getMyLists() {
    const data = await this.graphqlRequest('ListsManagementPageTimeline', { count: 100 });
    const lists = [];

    const instructions = data?.data?.viewer?.list_management_timeline?.timeline?.instructions || [];

    for (const inst of instructions) {
      for (const entry of (inst.entries || [])) {
        // Module items (suggestions)
        if (entry.content?.items) {
          for (const item of entry.content.items) {
            const listData = item?.item?.itemContent?.list;
            if (listData) lists.push(this.parseList(listData));
          }
        }
        // Direct list entries
        const listData = entry.content?.itemContent?.list;
        if (listData) lists.push(this.parseList(listData));
      }
    }

    return lists;
  }

  parseList(listData) {
    const owner = listData.user_results?.result || {};
    const ownerLegacy = owner.legacy || owner.core || {};

    return {
      id: listData.id_str,
      name: listData.name,
      description: listData.description || '',
      memberCount: listData.member_count,
      subscriberCount: listData.subscriber_count,
      mode: listData.mode,
      createdAt: listData.created_at,
      ownerHandle: ownerLegacy.screen_name,
      ownerName: ownerLegacy.name
    };
  }

  async getListInfo(listId) {
    const data = await this.graphqlRequest('ListByRestId', { listId });
    return this.parseList(data?.data?.list || {});
  }

  async getListMembersPage(listId, cursor = null) {
    const variables = { listId, count: 20 };
    if (cursor) variables.cursor = cursor;

    const data = await this.graphqlRequest('ListMembers', variables);

    const members = [];
    let nextCursor = null;

    const instructions = data?.data?.list?.members_timeline?.timeline?.instructions || [];

    for (const inst of instructions) {
      for (const entry of (inst.entries || [])) {
        const userResult = entry.content?.itemContent?.user_results?.result;
        if (userResult?.legacy) {
          members.push(this.parseMember(userResult));
        }

        if (entry.content?.cursorType === 'Bottom') {
          nextCursor = entry.content.value;
        }
      }
    }

    return { members, nextCursor };
  }

  parseMember(userResult) {
    const legacy = userResult.legacy || {};
    const core = userResult.core || {};
    const avatar = userResult.avatar || {};
    return {
      id: userResult.rest_id,
      handle: core.screen_name || legacy.screen_name,
      name: core.name || legacy.name,
      description: legacy.description || '',
      followersCount: legacy.followers_count,
      followingCount: legacy.friends_count,
      verified: userResult.is_blue_verified || false,
      profileImageUrl: avatar.image_url || legacy.profile_image_url_https,
      createdAt: core.created_at || legacy.created_at,
      location: legacy.location,
      url: legacy.url
    };
  }

  async getAllListMembers(listId, progressCallback = null) {
    const allMembers = [];
    let cursor = null;

    while (true) {
      const { members, nextCursor } = await this.getListMembersPage(listId, cursor);

      allMembers.push(...members);

      if (progressCallback) {
        progressCallback(allMembers.length);
      }

      if (!nextCursor || members.length === 0) break;
      cursor = nextCursor;

      // Small delay to avoid rate limiting
      await new Promise(r => setTimeout(r, 500));
    }

    return allMembers;
  }
}

async function checkConnection(cdpUrl) {
  try {
    const resp = await fetch(`${cdpUrl}/json/version`);
    const version = await resp.json();
    return { connected: true, browser: version.Browser };
  } catch (e) {
    return { connected: false, error: e.message };
  }
}

async function main() {
  const args = process.argv.slice(2);

  // Parse arguments
  let cdpUrl = 'http://localhost:9222';
  let discover = false;
  let listId = null;
  let listName = null;
  let output = 'list_export.json';
  let quiet = false;
  let check = false;

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--cdp-url':
        cdpUrl = args[++i];
        break;
      case '--discover':
        discover = true;
        break;
      case '--list-id':
      case '-l':
        listId = args[++i];
        break;
      case '--list-name':
      case '-n':
        listName = args[++i];
        break;
      case '--output':
      case '-o':
        output = args[++i];
        break;
      case '--quiet':
      case '-q':
        quiet = true;
        break;
      case '--check':
        check = true;
        break;
      case '--help':
      case '-h':
        console.log(`
X List Export Tool

Usage:
  node export_list.js [options]

Options:
  --cdp-url <url>     Chrome DevTools Protocol URL (default: http://localhost:9222)
  --check             Check browser connection
  --discover          List available X lists
  --list-id, -l <id>  List ID to export
  --list-name, -n <n> List name to export (partial match)
  --output, -o <file> Output JSON file (default: list_export.json)
  --quiet, -q         Suppress progress output
  --help, -h          Show this help

Examples:
  node export_list.js --check
  node export_list.js --discover
  node export_list.js --list-id 1876334018150678826 -o gauntlet.json
  node export_list.js --list-name "Gauntlet" -o gauntlet.json
`);
        process.exit(0);
    }
  }

  // Check connection
  const status = await checkConnection(cdpUrl);
  if (!status.connected) {
    console.error(`✗ Cannot connect to browser at ${cdpUrl}`);
    console.error(`  ${status.error}`);
    console.error('\nStart Chrome with: chrome --remote-debugging-port=9222');
    process.exit(1);
  }

  if (!quiet) console.log(`✓ Connected to ${status.browser}`);

  // Connect to browser
  const browser = await puppeteer.connect({
    browserURL: cdpUrl,
    defaultViewport: null
  });

  try {
    // Find or create a page for API calls
    const pages = await browser.pages();
    let page = pages.find(p => p.url().includes('x.com'));

    if (!page) {
      page = await browser.newPage();
      await page.goto('https://x.com', { waitUntil: 'networkidle2' });
    }

    // Get cookies
    const cookies = await page.cookies();
    const authToken = cookies.find(c => c.name === 'auth_token');
    const csrfToken = cookies.find(c => c.name === 'ct0');

    if (!authToken || !csrfToken) {
      console.error('✗ Not logged into X. Please log in at x.com first.');
      process.exit(1);
    }

    if (!quiet) console.log('✓ Auth extracted');

    const api = new XListsAPI(browser, page, cookies);

    if (check && !discover && !listId && !listName) {
      console.log('\nRun with --discover to see available lists');
      return;
    }

    // Discover lists
    if (discover) {
      if (!quiet) console.log('\nFetching your lists...');

      const lists = await api.getMyLists();

      console.log(`\nFound ${lists.length} lists:\n`);

      for (const lst of lists) {
        const icon = lst.mode === 'Private' ? '🔒' : '🌐';
        console.log(`  ${icon} ${lst.name}`);
        console.log(`     ID: ${lst.id}`);
        console.log(`     Members: ${lst.memberCount}`);
        if (lst.ownerHandle) console.log(`     Owner: @${lst.ownerHandle}`);
        console.log();
      }

      console.log('To export a list:');
      console.log('  node export_list.js --list-id <ID> -o export.json');
      return;
    }

    // Find list by name
    if (listName && !listId) {
      const lists = await api.getMyLists();
      const matches = lists.filter(l => l.name.toLowerCase().includes(listName.toLowerCase()));

      if (matches.length === 0) {
        console.error(`No list found matching '${listName}'`);
        console.error('Run with --discover to see available lists');
        process.exit(1);
      }

      if (matches.length > 1) {
        console.error(`Multiple lists match '${listName}':`);
        for (const lst of matches) {
          console.error(`  - ${lst.name} (ID: ${lst.id})`);
        }
        console.error('\nUse --list-id to specify which one.');
        process.exit(1);
      }

      listId = matches[0].id;
      if (!quiet) console.log(`Found list: ${matches[0].name}`);
    }

    if (!listId) {
      console.error('Please specify --list-id or --list-name');
      console.error('Run with --discover to see available lists');
      process.exit(1);
    }

    // Export the list
    if (!quiet) console.log(`\nExporting list ${listId}...`);

    const listInfo = await api.getListInfo(listId);

    const members = await api.getAllListMembers(listId, (count) => {
      if (!quiet) process.stdout.write(`  Fetched ${count} members...\r`);
    });

    const exportData = {
      list: listInfo,
      exportedAt: new Date().toISOString(),
      memberCount: members.length,
      members
    };

    fs.writeFileSync(output, JSON.stringify(exportData, null, 2));

    if (!quiet) {
      console.log(`\n✓ Exported ${members.length} members to ${output}`);
      console.log(`  List: ${listInfo.name}`);
    }

  } finally {
    browser.disconnect();
  }
}

main().catch(e => {
  console.error('Error:', e.message);
  process.exit(1);
});
