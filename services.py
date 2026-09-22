# services.py — by idqwixxa

import re

SERVICES = {
    "binance": {
        "name": "Binance",
        "priority": 10,
        "strong": ["p20t", "bnc-uuid"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["p20t"],
        "required_any": [],
        "weak": ["cr00", "BNC_FV", "logined"],
    },
    "coinbase": {
        "name": "Coinbase",
        "priority": 10,
        "strong": ["cb_did"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["cb_did"],
        "required_any": [],
        "weak": ["coinbase_session", "_cb_sid"],
    },
    "paypal": {
        "name": "PayPal",
        "priority": 10,
        "strong": ["x-pp-s", "_paypal_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["x-pp-s"],
        "required_any": [],
        "weak": ["cookie_check", "nsid", "AKDC"],
    },
    "stripe": {
        "name": "Stripe",
        "priority": 10,
        "strong": ["private_machine_identifier", "site-auth"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["private_machine_identifier", "site-auth"],
        "weak": ["stripe.csrf", "__stripe_mid", "__stripe_sid"],
    },
    "kraken": {
        "name": "Kraken",
        "priority": 10,
        "strong": ["kraken_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["kraken_session"],
        "weak": ["session_id", "kraken_uid", "cf_clearance"],
    },
    "metamask": {
        "name": "MetaMask",
        "priority": 8,
        "strong": ["metamask_session", "metamask_user"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["metamask_session", "metamask_user"],
        "weak": ["metamask_wallet", "mm_session"],
    },
    "trustwallet": {
        "name": "Trust Wallet",
        "priority": 8,
        "strong": ["trustwallet_session", "tw_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["trustwallet_session", "tw_session"],
        "weak": ["trust_wallet", "tw_uid"],
    },
    "opensea": {
        "name": "OpenSea",
        "priority": 10,
        "strong": ["opensea_session", "os_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["opensea_session", "os_session"],
        "weak": ["os_profile", "opensea_wallet"],
    },
    "telegram": {
        "name": "Telegram (Web)",
        "priority": 10,
        "strong": ["stel_ssid", "stel_token"],
        "strong_prefixes": ["stel_"],
        "value_patterns": {},
        "required": [],
        "required_any": ["stel_ssid", "stel_token"],
        "weak": ["stel_dt", "stel_ton_token", "stel_web_auth"],
    },
    "instagram": {
        "name": "Instagram",
        "priority": 10,
        "strong": ["ds_user_id", "ig_did"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["sessionid", "ds_user_id"],
        "required_any": [],
        "weak": ["csrftoken", "mid", "rur", "ig_nrcb", "shbid", "shbts"],
    },
    "facebook": {
        "name": "Facebook",
        "priority": 10,
        "strong": ["c_user"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["c_user", "xs"],
        "required_any": [],
        "weak": ["fr", "datr", "sb", "presence"],
    },
    "vk": {
        "name": "VK",
        "priority": 10,
        "strong": ["remixsid"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["remixsid"],
        "required_any": [],
        "weak": ["remixlang", "remixlhk", "remixnsid", "remixstid"],
    },
    "whatsapp": {
        "name": "WhatsApp (Web)",
        "priority": 10,
        "strong": ["wa_web_initial_version", "wa_csrf"],
        "strong_prefixes": ["wa_"],
        "value_patterns": {},
        "required": [],
        "required_any": ["wa_web_initial_version", "wa_csrf"],
        "weak": ["wa_lang_pref", "wa_browser_id"],
    },
    "discord": {
        "name": "Discord",
        "priority": 9,
        "strong": [],
        "strong_prefixes": [],
        "value_patterns": {
            "token": r"^[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{20,}$",
            "discord_token": r"^[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{20,}$",
        },
        "required": [],
        "required_any": [],
        "weak": ["__dcfduid", "__sdcfduid", "__cfruid", "_cfuvid"],
    },
    "twitter": {
        "name": "Twitter/X",
        "priority": 10,
        "strong": ["auth_token"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["auth_token", "ct0"],
        "required_any": [],
        "weak": ["twid", "kdt", "guest_id", "personalization_id"],
    },
    "reddit": {
        "name": "Reddit",
        "priority": 10,
        "strong": ["reddit_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["reddit_session"],
        "required_any": [],
        "weak": ["token_v2", "csv", "edgebucket", "session_tracker"],
    },
    "linkedin": {
        "name": "LinkedIn",
        "priority": 10,
        "strong": ["li_at"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["li_at"],
        "required_any": [],
        "weak": ["JSESSIONID", "li_rm", "lang", "bcookie"],
    },
    "tiktok": {
        "name": "TikTok",
        "priority": 8,
        "strong": ["sid_tt", "sessionid_ss", "sid_guard", "sessionid"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["sessionid", "sessionid_ss", "sid_tt"],
        "weak": ["ttwid", "passport_csrf_token", "uid_tt", "uid_tt_ss",
                 "tt_csrf_token", "msToken"],
    },
    "twitch": {
        "name": "Twitch",
        "priority": 8,
        "strong": ["auth-token"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["auth-token"],
        "required_any": [],
        "weak": ["twilight-user", "persistent", "unique_id", "api_token"],
    },
    "netflix": {
        "name": "Netflix",
        "priority": 10,
        "strong": ["NetflixId", "SecureNetflixId"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["NetflixId"],
        "required_any": [],
        "weak": ["nfvdid", "flwssn", "memclid"],
    },
    "spotify": {
        "name": "Spotify",
        "priority": 10,
        "strong": ["sp_dc", "sp_key"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["sp_dc"],
        "required_any": [],
        "weak": ["sp_t", "sp_landing", "sp_gaid", "OptanonConsent"],
    },
    "google": {
        "name": "Google Workspace",
        "priority": 10,
        "strong": ["SID", "HSID"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["SID", "HSID", "SSID"],
        "required_any": [],
        "weak": ["APISID", "SAPISID", "__Secure-1PSID",
                 "__Secure-3PSID", "SIDCC"],
    },
    "microsoft365": {
        "name": "Microsoft 365",
        "priority": 10,
        "strong": ["__Host-MSAAUTHP", "MSPAuth"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["__Host-MSAAUTHP", "MSPAuth"],
        "weak": ["RPSSecAuth", "MSPRequ", "MSPOK", "MSPProf"],
    },
    "proton": {
        "name": "Proton Mail",
        "priority": 10,
        "strong": [],
        "strong_prefixes": ["AUTH-", "REFRESH-"],
        "value_patterns": {},
        "required": [],
        "required_any": [],
        "weak": ["proton_uid", "session-uid"],
    },
    "yahoo": {
        "name": "Yahoo Mail",
        "priority": 10,
        "strong": ["A1", "A1S"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["A1"],
        "required_any": [],
        "weak": ["A3", "B", "Y", "GUC"],
    },
    "mailru": {
        "name": "Mail.ru",
        "priority": 10,
        "strong": ["Mpop"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["Mpop"],
        "required_any": [],
        "weak": ["video_key", "act", "VKcookie"],
    },
    "slack": {
        "name": "Slack",
        "priority": 10,
        "strong": ["d-s"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["d-s"],
        "required_any": [],
        "weak": ["OptanonConsent", "b", "d"],
    },
    "jira": {
        "name": "Jira",
        "priority": 10,
        "strong": ["cloud.session.token", "atlassian.xsrf.token"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["cloud.session.token", "atlassian.xsrf.token"],
        "weak": ["JSESSIONID", "seraph.rememberme.cookie",
                 "studio.crowd.tokenkey"],
    },
    "notion": {
        "name": "Notion",
        "priority": 10,
        "strong": ["token_v2"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["token_v2"],
        "required_any": [],
        "weak": ["notion_user_id", "notion_browser_id",
                 "notion_check_cookie"],
    },
    "trello": {
        "name": "Trello",
        "priority": 9,
        "strong": ["token"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["token"],
        "weak": ["trello_session", "dsc", "preAuthProps"],
    },
    "dropbox": {
        "name": "Dropbox",
        "priority": 9,
        "strong": ["jar"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["jar"],
        "required_any": [],
        "weak": ["t", "__Host-js_csrf", "dropbox_uid"],
    },
    "github": {
        "name": "GitHub",
        "priority": 10,
        "strong": ["user_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["user_session"],
        "required_any": [],
        "weak": ["logged_in", "_gh_sess", "dotcom_user",
                 "preferred_color_mode"],
    },
    "gitlab": {
        "name": "GitLab",
        "priority": 10,
        "strong": ["_gitlab_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["_gitlab_session"],
        "required_any": [],
        "weak": ["gitlab_canary", "known_sign_in", "_gitlab_session_id"],
    },
    "bitbucket": {
        "name": "Bitbucket",
        "priority": 10,
        "strong": ["bitbucket-session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["bitbucket-session"],
        "weak": ["atl_user_id", "bb_session", "cloud.session.token"],
    },
    "aws": {
        "name": "AWS",
        "priority": 10,
        "strong": ["aws-userInfo", "aws-creds"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["aws-userInfo", "aws-creds"],
        "weak": ["noflush_awsc-0", "session-id", "aws-session"],
    },
    "azure": {
        "name": "Azure",
        "priority": 10,
        "strong": ["ESTSAUTHPERSISTENT", "ESTSAUTH"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["ESTSAUTHPERSISTENT", "ESTSAUTH"],
        "weak": ["__Host-MSAAUTHP", "RPSSecAuth", "brcap"],
    },
    "digitalocean": {
        "name": "DigitalOcean",
        "priority": 10,
        "strong": ["_digitalocean", "DO_SESSION"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["_digitalocean", "DO_SESSION"],
        "weak": ["do_csrf", "_do_session"],
    },
    "cloudflare": {
        "name": "Cloudflare Dashboard",
        "priority": 10,
        "strong": ["__cf_dashboard_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["__cf_dashboard_session"],
        "weak": ["cf_clearance", "__cf_bm", "__cfruid"],
    },
    "steam": {
        "name": "Steam",
        "priority": 10,
        "strong": ["steamLoginSecure", "steamLogin"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["steamLoginSecure"],
        "required_any": [],
        "weak": ["sessionid", "steamCountry", "steamMachineAuth",
                 "steamRememberLogin"],
    },
    "epic": {
        "name": "Epic Games",
        "priority": 10,
        "strong": ["EPIC_SSO", "EPIC_BEARER"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["EPIC_SSO"],
        "required_any": [],
        "weak": ["EPIC_SSO_RM", "EPIC_SESSION", "EPIC_DEVICE"],
    },
    "riot": {
        "name": "Riot Games",
        "priority": 8,
        "strong": ["ssid", "sub"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["ssid"],
        "required_any": [],
        "weak": ["clid", "csid", "tdid", "ccid"],
    },
    "battlenet": {
        "name": "Battle.net",
        "priority": 9,
        "strong": ["BAYEUX_BROWSER"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["BAYEUX_BROWSER"],
        "required_any": [],
        "weak": ["XSRF-TOKEN", "_blizzard_web"],
    },
    "xbox": {
        "name": "Xbox",
        "priority": 9,
        "strong": ["XBL3.0"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["XBL3.0"],
        "required_any": [],
        "weak": ["MSCC", "__Host-MSAAUTH"],
    },
    "roblox": {
        "name": "Roblox",
        "priority": 10,
        "strong": [".ROBLOSECURITY"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [".ROBLOSECURITY"],
        "required_any": [],
        "weak": [".RBXID", ".RBXSESSION", "RBXEventTrackerV2"],
    },
    "amazon": {
        "name": "Amazon",
        "priority": 8,
        "strong": ["session-token", "at-main"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["session-id"],
        "required_any": [],
        "weak": ["session-id-time", "ubid-main", "x-main", "lc-main"],
    },
    "ebay": {
        "name": "eBay",
        "priority": 9,
        "strong": ["ebay", "dp1"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["ebay"],
        "required_any": [],
        "weak": ["s", "nonsession", "bm_sv"],
    },
    "airbnb": {
        "name": "Airbnb",
        "priority": 10,
        "strong": ["_aat"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": ["_aat"],
        "required_any": [],
        "weak": ["_airbed_session_id", "_user_attributes"],
    },
    "openvpn": {
        "name": "OpenVPN",
        "priority": 8,
        "strong": ["_openvpn_session", "_openvpn_pf"],
        "strong_prefixes": ["_openvpn"],
        "value_patterns": {},
        "required": [],
        "required_any": ["_openvpn_session", "_openvpn_pf"],
        "weak": ["openvpn_csrf", "ovpn_session"],
    },
    "wireguard": {
        "name": "WireGuard",
        "priority": 8,
        "strong": ["wg_session", "wireguard_session"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["wg_session", "wireguard_session"],
        "weak": ["wg_csrf", "wireguard_uid"],
    },
    "adminer": {
        "name": "Adminer",
        "priority": 9,
        "strong": ["adminer_sid", "adminer_key"],
        "strong_prefixes": [],
        "value_patterns": {},
        "required": [],
        "required_any": ["adminer_sid", "adminer_key"],
        "weak": ["adminer_version", "adminer_permanent"],
    },
    "phpmyadmin": {
        "name": "phpMyAdmin",
        "priority": 9,
        "strong": ["phpMyAdmin", "pmaAuth-1"],
        "strong_prefixes": ["pmaAuth", "pmaUser"],
        "value_patterns": {},
        "required": [],
        "required_any": ["phpMyAdmin", "pmaAuth-1"],
        "weak": ["pmaUser-1", "pma_lang", "pma_theme"],
    },
}


def _weak_score(service_key, names):
    return sum(1 for w in SERVICES[service_key].get("weak", []) if w in names)


def _has_prefix(service_key, names):
    prefixes = SERVICES[service_key].get("strong_prefixes") or []
    if not prefixes:
        return False
    for n in names:
        for p in prefixes:
            if n.startswith(p):
                return True
    return False


def _matches_patterns(service_key, jar):
    patterns = SERVICES[service_key].get("value_patterns") or {}
    if not patterns:
        return False
    for key, rx in patterns.items():
        if key in jar:
            try:
                if re.match(rx, str(jar[key])):
                    return True
            except re.error:
                continue
    return False


def _all_required_present(info, names):
    req = info.get("required") or []
    if req and not all(r in names for r in req):
        return False

    req_any = info.get("required_any") or []
    if req_any and not any(r in names for r in req_any):
        return False

    return True


def _score(service_key, names):
    prio = SERVICES[service_key].get("priority", 0)
    wscore = _weak_score(service_key, names)
    return (prio, wscore)


def _pick_best(candidates, names):
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return max(candidates, key=lambda k: _score(k, names))


def detect_service(jar):
    if not jar:
        return None
    names = set(jar.keys())

    strong_matches = [
        k for k, info in SERVICES.items()
        if any(s in names for s in info.get("strong", []))
        and _all_required_present(info, names)
    ]
    if strong_matches:
        return _pick_best(strong_matches, names)

    prefix_matches = [
        k for k, info in SERVICES.items()
        if _has_prefix(k, names)
        and _all_required_present(info, names)
    ]
    if prefix_matches:
        return _pick_best(prefix_matches, names)

    pattern_matches = [
        k for k, info in SERVICES.items()
        if _matches_patterns(k, jar)
    ]
    if pattern_matches:
        return _pick_best(pattern_matches, names)

    req_matches = [
        k for k, info in SERVICES.items()
        if (info.get("required") or info.get("required_any"))
        and _all_required_present(info, names)
    ]
    if req_matches:
        return _pick_best(req_matches, names)

    weak_matches = [
        k for k, info in SERVICES.items()
        if _weak_score(k, names) >= 2
    ]
    return _pick_best(weak_matches, names)