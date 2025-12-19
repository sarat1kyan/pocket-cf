import requests
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from config import config
import logging

logger = logging.getLogger(__name__)
ISO = "%Y-%m-%dT%H:%M:%SZ"

class CloudflareAPI:
    def __init__(self):
        self.rest_base = "https://api.cloudflare.com/client/v4"
        self.graphql_url = f"{self.rest_base}/graphql"
        self.headers = {
            "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    # ---------- generic REST helpers ----------
    def _rest(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
              json: Optional[Any] = None, timeout: int = 45) -> Optional[Dict[str, Any]]:
        url = f"{self.rest_base}/{path.lstrip('/')}"
        try:
            resp = requests.request(method.upper(), url, headers=self.headers, params=params, json=json, timeout=timeout)
            logger.debug("REST %s %s -> %s", method.upper(), path, resp.status_code)
            
            if resp.status_code == 404:
                logger.warning("Resource not found: %s", path)
                return {"success": False, "status": 404}
            
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get("success", True):
                errors = data.get("errors", [])
                error_messages = [err.get("message", str(err)) for err in errors]
                logger.error("Cloudflare API error(s) for %s %s: %s", method.upper(), path, error_messages)
                return None
            
            return data
        except requests.exceptions.Timeout:
            logger.error("API Request timeout for %s %s (timeout: %ds)", method.upper(), path, timeout)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("API Connection error for %s %s: %s", method.upper(), path, e)
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("API HTTP error for %s %s: %s (status: %s)", method.upper(), path, e, resp.status_code if 'resp' in locals() else 'unknown')
            return None
        except requests.RequestException as e:
            logger.error("API Request failed for %s %s: %s", method.upper(), path, e, exc_info=True)
            return None
        except Exception as e:
            logger.error("Unexpected error in API request for %s %s: %s", method.upper(), path, e, exc_info=True)
            return None

    def _rest_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return self._rest("GET", path, params=params)

    def _rest_post(self, path: str, payload: Any) -> Optional[Dict[str, Any]]:
        return self._rest("POST", path, json=payload)

    def _rest_patch(self, path: str, payload: Any) -> Optional[Dict[str, Any]]:
        return self._rest("PATCH", path, json=payload)

    def _rest_put(self, path: str, payload: Any) -> Optional[Dict[str, Any]]:
        return self._rest("PUT", path, json=payload)

    def _rest_delete(self, path: str) -> Optional[Dict[str, Any]]:
        return self._rest("DELETE", path)

    def _graphql(self, query: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = {"query": query, "variables": variables}
        try:
            resp = requests.post(self.graphql_url, headers=self.headers, json=payload, timeout=45)
            logger.debug("GraphQL status: %s", resp.status_code)
            
            # Check for authentication errors first
            if resp.status_code == 401:
                logger.error("GraphQL authentication failed (401). Check your CLOUDFLARE_API_TOKEN.")
                logger.error("Token format: %s...", config.CLOUDFLARE_API_TOKEN[:20] if config.CLOUDFLARE_API_TOKEN else "None")
                return None
            
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                error_messages = [err.get("message", str(err)) for err in data["errors"]]
                logger.error("GraphQL error(s): %s", error_messages)
                # Log more details about the error
                for err in data.get("errors", []):
                    if err.get("message"):
                        logger.error("  - %s", err.get("message"))
                    if err.get("path"):
                        logger.error("  - Path: %s", err.get("path"))
                return None
            return data
        except requests.exceptions.Timeout:
            logger.error("GraphQL request timeout")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("GraphQL connection error: %s", e)
            return None
        except requests.exceptions.HTTPError as e:
            status_code = resp.status_code if 'resp' in locals() else 'unknown'
            logger.error("GraphQL HTTP error: %s (status: %s)", e, status_code)
            if 'resp' in locals() and resp.status_code == 401:
                logger.error("Authentication failed. Please verify your CLOUDFLARE_API_TOKEN is valid and has Analytics permissions.")
            elif 'resp' in locals() and resp.status_code == 403:
                logger.error("Access forbidden. Check that your API token has Zone.Analytics (Read) permission.")
            try:
                error_detail = resp.json() if 'resp' in locals() else {}
                if error_detail.get("errors"):
                    for err in error_detail["errors"]:
                        logger.error("  API Error: %s", err.get("message", str(err)))
            except:
                pass
            return None
        except requests.RequestException as e:
            logger.error("GraphQL request failed: %s", e, exc_info=True)
            return None
        except Exception as e:
            logger.error("Unexpected error in GraphQL request: %s", e, exc_info=True)
            return None

    # ========================= ZONES =========================
    def list_zones(self, page: int = 1, per_page: int = 50, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        params: Dict[str, Any] = {"page": page, "per_page": per_page, "status": "active"}
        if name:
            params["name"] = name
        return self._rest_get("zones", params=params)

    def get_zone_details(self, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        if not zid:
            logger.error("No zone ID provided to get_zone_details")
            return None
        result = self._rest_get(f"zones/{zid}")
        if not result:
            logger.warning(f"Failed to get zone details for zone ID: {zid[:8]}...")
            logger.warning("Possible causes:")
            logger.warning("  - Zone ID is incorrect")
            logger.warning("  - API token doesn't have Zone.Zone (Read) permission")
            logger.warning("  - Zone doesn't exist or you don't have access to it")
        return result

    # ==================== GRAPHQL ANALYTICS ==================
    def _get_zone_tag(self, zone_id: Optional[str] = None) -> Optional[str]:
        """Get zone tag (ID or name) for GraphQL queries.
        
        Cloudflare GraphQL API accepts zoneTag as either:
        - Zone ID (32 char hex) - preferred and more reliable
        - Zone name (domain) - may not work in all cases
        
        We'll use zone ID directly if available, otherwise try to get it from zone name.
        """
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        if not zid:
            logger.error("No zone ID provided")
            return None
        
        # If it looks like a zone ID (32 char hex), use it directly
        if len(zid) == 32 and all(c in '0123456789abcdefABCDEF' for c in zid):
            logger.debug(f"Using zone ID directly as zoneTag: {zid[:8]}...")
            return zid
        
        # Otherwise, it might be a zone name - try to get zone ID from it
        # But first, let's try using it as-is (some GraphQL queries accept zone names)
        logger.debug(f"Input appears to be zone name, trying to resolve to zone ID: {zid}")
        try:
            # Try to find zone by name
            zones = self.list_zones(name=zid, per_page=1)
            if zones and zones.get("result") and len(zones["result"]) > 0:
                found_zone_id = zones["result"][0].get("id")
                if found_zone_id:
                    logger.debug(f"Resolved zone name {zid} to zone ID {found_zone_id[:8]}...")
                    return found_zone_id
        except Exception as e:
            logger.warning(f"Error resolving zone name to ID: {e}")
        
        # Fallback: try using the input as-is (might be zone ID in different format)
        logger.debug(f"Using input as-is for zoneTag: {zid}")
        return zid
    
    def get_http_requests_fixed(self, hours: int = 24, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime(ISO)
        end = now.strftime(ISO)
        zone_tag = self._get_zone_tag(zone_id)
        if not zone_tag:
            logger.error("Failed to get zone tag for GraphQL query")
            return None
        query = """
        query TrafficSeries($zoneTag: String!, $start: Time!, $end: Time!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              httpRequestsAdaptiveGroups(
                limit: 2000
                orderBy: [datetime_ASC]
                filter: { datetime_geq: $start, datetime_leq: $end }
              ) {
                count
                sum { edgeResponseBytes visits }
                dimensions { datetime }
              }
            }
          }
        }
        """
        return self._graphql(query, {"zoneTag": zone_tag, "start": start, "end": end})

    def get_analytics_by_colo(self, hours: int = 24, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime(ISO)
        end = now.strftime(ISO)
        zone_tag = self._get_zone_tag(zone_id)
        if not zone_tag:
            logger.error("Failed to get zone tag for GraphQL query")
            return None
        query = """
        query ColoBreakdown($zoneTag: String!, $start: Time!, $end: Time!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              httpRequestsAdaptiveGroups(
                limit: 2000
                filter: { datetime_geq: $start, datetime_leq: $end }
              ) {
                count
                sum { edgeResponseBytes }
                dimensions { coloCode }
              }
            }
          }
        }
        """
        return self._graphql(query, {"zoneTag": zone_tag, "start": start, "end": end})

    def get_security_events(self, hours: int = 24, limit: int = 200, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime(ISO)
        end = now.strftime(ISO)
        zone_tag = self._get_zone_tag(zone_id)
        if not zone_tag:
            logger.error("Failed to get zone tag for GraphQL query")
            return None
        query = f"""
        query SecurityEvents($zoneTag: String!, $start: Time!, $end: Time!) {{
          viewer {{
            zones(filter: {{ zoneTag: $zoneTag }}) {{
              firewallEventsAdaptiveGroups(
                limit: {limit}
                orderBy: [count_DESC]
                filter: {{ datetime_geq: $start, datetime_leq: $end }}
              ) {{
                count
                dimensions {{ action ruleId source clientIP }}
              }}
            }}
          }}
        }}
        """
        return self._graphql(query, {"zoneTag": zone_tag, "start": start, "end": end})

    def get_http_by_cache_status(self, hours: int = 24, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime(ISO)
        end = now.strftime(ISO)
        zone_tag = self._get_zone_tag(zone_id)
        if not zone_tag:
            logger.error("Failed to get zone tag for GraphQL query")
            return None
        query = """
        query CacheStatusSplit($zoneTag: String!, $start: Time!, $end: Time!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              httpRequestsAdaptiveGroups(
                limit: 1000
                filter: { datetime_geq: $start, datetime_leq: $end }
              ) {
                count
                dimensions { cacheStatus }
              }
            }
          }
        }
        """
        return self._graphql(query, {"zoneTag": zone_tag, "start": start, "end": end})

    def get_top_mitigated_ips(self, hours: int = 24, limit: int = 10, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).strftime(ISO)
        end = now.strftime(ISO)
        zone_tag = self._get_zone_tag(zone_id)
        if not zone_tag:
            logger.error("Failed to get zone tag for GraphQL query")
            return None
        query = f"""
        query TopMitigatedIPs($zoneTag: String!, $start: Time!, $end: Time!) {{
          viewer {{
            zones(filter: {{ zoneTag: $zoneTag }}) {{
              firewallEventsAdaptiveGroups(
                limit: {limit}
                orderBy: [count_DESC]
                filter: {{
                  datetime_geq: $start,
                  datetime_leq: $end,
                  action_in: [block, challenge, js_challenge, managed_challenge]
                }}
              ) {{
                count
                dimensions {{ clientIP }}
              }}
            }}
          }}
        }}
        """
        return self._graphql(query, {"zoneTag": zone_tag, "start": start, "end": end})

    # -------- DNS analytics (REST)
    def get_dns_analytics_report(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        metrics: str = "queryCount,responseTimeAvg",
        dimensions: str = "responseCode,queryType",
        zone_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        params: Dict[str, Any] = {"metrics": metrics, "dimensions": dimensions, "limit": 1000}
        if since: params["since"] = since.astimezone(timezone.utc).strftime(ISO)
        if until: params["until"] = until.astimezone(timezone.utc).strftime(ISO)
        return self._rest_get(f"zones/{zid}/dns_analytics/report", params=params)

    # ===================== ACCESS RULES (IP) =================
    def list_access_rules(self, page: int = 1, per_page: int = 50,
                          mode: Optional[str] = None,
                          notes: Optional[str] = None,
                          configuration_value: Optional[str] = None,
                          zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if mode: params["mode"] = mode
        if notes: params["notes"] = notes
        if configuration_value: params["configuration.value"] = configuration_value
        return self._rest_get(f"zones/{zid}/firewall/access_rules/rules", params=params)

    def create_access_rule(self, mode: str, target: str, value: str, notes: str = "", zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        payload = {"mode": mode, "configuration": {"target": target, "value": value}, "notes": notes}
        return self._rest_post(f"zones/{zid}/firewall/access_rules/rules", payload)

    def update_access_rule(self, rule_id: str, mode: Optional[str] = None, notes: Optional[str] = None, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        body: Dict[str, Any] = {}
        if mode is not None: body["mode"] = mode
        if notes is not None: body["notes"] = notes
        return self._rest_patch(f"zones/{zid}/firewall/access_rules/rules/{rule_id}", body)

    def delete_access_rule(self, rule_id: str, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        resp = self._rest_delete(f"zones/{zid}/firewall/access_rules/rules/{rule_id}")
        return bool(resp)

    # ===================== FIREWALL RULES (custom) ===========
    def list_filters(self, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_get(f"zones/{zid}/filters")

    def create_filter(self, expression: str, description: str = "", zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_post(f"zones/{zid}/filters", [{"expression": expression, "description": description}])

    def delete_filter(self, filter_id: str, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return bool(self._rest_delete(f"zones/{zid}/filters/{filter_id}"))

    def list_firewall_rules(self, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_get(f"zones/{zid}/firewall/rules")

    def create_firewall_rule(self, filter_id: str, action: str, description: str = "", products: Optional[List[str]] = None,
                             paused: bool = False, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        body: Dict[str, Any] = {"filter": {"id": filter_id}, "action": action, "paused": paused, "description": description}
        if action.lower() in {"bypass", "skip"} and products:
            body["products"] = products
        return self._rest_post(f"zones/{zid}/firewall/rules", [body])

    def update_firewall_rule(self, rule_id: str, *, paused: Optional[bool] = None, action: Optional[str] = None,
                             description: Optional[str] = None, products: Optional[List[str]] = None, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        body: Dict[str, Any] = {"id": rule_id}
        if paused is not None: body["paused"] = paused
        if action is not None: body["action"] = action
        if description is not None: body["description"] = description
        if action in {"bypass", "skip"} and products is not None:
            body["products"] = products
        return self._rest_patch(f"zones/{zid}/firewall/rules/{rule_id}", body)

    def delete_firewall_rule(self, rule_id: str, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return bool(self._rest_delete(f"zones/{zid}/firewall/rules/{rule_id}"))

    # ===================== CACHE =============================
    def purge_cache_everything(self, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return bool(self._rest_post(f"zones/{zid}/purge_cache", {"purge_everything": True}))

    def purge_cache_files(self, files: List[str], zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return bool(self._rest_post(f"zones/{zid}/purge_cache", {"files": files}))

    # ===================== DNS (CRUD) ========================
    def list_dns_records(self, name: Optional[str] = None, type: Optional[str] = None,
                         page: int = 1, per_page: int = 100, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        params: Dict[str, Any] = {"page": page, "per_page": per_page}
        if name: params["name"] = name
        if type: params["type"] = type
        return self._rest_get(f"zones/{zid}/dns_records", params=params)

    def create_dns_record(self, type: str, name: str, content: str, ttl: int = 1, proxied: Optional[bool] = True, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        body: Dict[str, Any] = {"type": type, "name": name, "content": content, "ttl": ttl}
        if proxied is not None: body["proxied"] = proxied
        return self._rest_post(f"zones/{zid}/dns_records", body)

    def update_dns_record(self, record_id: str, zone_id: Optional[str] = None, **fields) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_patch(f"zones/{zid}/dns_records/{record_id}", fields)

    def delete_dns_record(self, record_id: str, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return bool(self._rest_delete(f"zones/{zid}/dns_records/{record_id}"))

    # ===================== RULESETS: RATE LIMITING ===========
    def _get_ratelimit_entrypoint(self, zone_id: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        data = self._rest_get(f"zones/{zid}/rulesets/phases/http_ratelimit/entrypoint")
        if not data:
            return (None, None)
        rid = (data.get("result") or {}).get("id")
        return (rid, data)

    def list_ratelimit_rules(self, zone_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rid, data = self._get_ratelimit_entrypoint(zone_id=zone_id)
        if not rid or not data:
            return []
        rules = (data.get("result") or {}).get("rules", []) or []
        return rules

    def add_ratelimit_rule(
        self,
        expression: str,
        requests_per_period: int,
        period: int,
        mitigation_timeout: int = 600,
        *,
        action: str = "block",
        characteristics: Optional[List[str]] = None,
        requests_to_origin: Optional[bool] = None,
        custom_response: Optional[Dict[str, Any]] = None,
        zone_id: Optional[str] = None,
        description: str = "Rate limit",
    ) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        characteristics = characteristics or ["ip.src"]

        rule: Dict[str, Any] = {
            "description": description,
            "expression": expression,
            "action": action,
            "ratelimit": {
                "characteristics": characteristics,
                "period": int(period),
                "requests_per_period": int(requests_per_period),
                "mitigation_timeout": int(mitigation_timeout),
            },
        }
        if requests_to_origin is True:
            rule["ratelimit"]["requests_to_origin"] = True
        if custom_response:
            rule["action_parameters"] = {"response": custom_response}

        rid, _ = self._get_ratelimit_entrypoint(zone_id=zid)
        if rid:
            return self._rest_post(f"zones/{zid}/rulesets/{rid}/rules", rule)
        else:
            payload = {
                "name": "Zone rate limiting",
                "description": "Rate limiting rules (created by bot)",
                "kind": "zone",
                "phase": "http_ratelimit",
                "rules": [rule],
            }
            return self._rest_post(f"zones/{zid}/rulesets", payload)

    def delete_ratelimit_rule(self, rule_id: str, zone_id: Optional[str] = None) -> bool:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        rid, _ = self._get_ratelimit_entrypoint(zone_id=zid)
        if not rid:
            return False
        resp = self._rest_delete(f"zones/{zid}/rulesets/{rid}/rules/{rule_id}")
        return bool(resp)

    # ===================== SETTINGS (BFM) ====================
    def get_setting(self, setting: str, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_get(f"zones/{zid}/settings/{setting}")

    def set_setting(self, setting: str, value: Any, zone_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        zid = zone_id or config.CLOUDFLARE_ZONE_ID
        return self._rest_patch(f"zones/{zid}/settings/{setting}", {"value": value})

    def set_bfm(self, on: bool, zone_id: Optional[str] = None) -> bool:
        return bool(self.set_setting("bot_fight_mode", "on" if on else "off", zone_id=zone_id))

    def set_sbfm(self, on: bool, zone_id: Optional[str] = None) -> bool:
        return bool(self.set_setting("super_bot_fight_mode", "on" if on else "off", zone_id=zone_id))


cf_api = CloudflareAPI()
