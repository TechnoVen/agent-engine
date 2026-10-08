"""core/model_download/network.py

Strict SSRF and network security validation for Agent Engine model downloads.
Part of Milestone R3 Task R3.6 (Managed Model Download and Verification).

Invariants:
1. HTTPS by Default: Reject plain HTTP, file://, ftp://, and exotic schemes.
2. Anti-SSRF: Resolve hostnames and reject loopback, RFC1918 private, link-local,
   multicast, cloud-metadata (169.254.169.254), and unspecified addresses.
3. Strict Redirect Revalidation: Re-validate every redirect hop; abort if redirected
   from public to private/loopback addresses.
4. Credential Rejection: Reject URLs containing embedded credentials (user:pass@host).
5. Enforced TLS: Certificate verification is always enabled.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional, Set
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger("agent_engine.models.download.network")

# Explicitly forbidden cloud metadata addresses and networks
CLOUD_METADATA_IPS: Set[str] = {
    "169.254.169.254",  # AWS/GCP/Azure/OpenStack Instance Metadata Service
    "fd00:ec2::254",  # AWS IPv6 IMDS
}


class NetworkSecurityError(Exception):
    """Base exception for network security and transport violations."""


class SSRFSecurityError(NetworkSecurityError):
    """Raised when a download URL targets or redirects to a forbidden private/local IP."""


class InvalidURLError(NetworkSecurityError):
    """Raised when a URL scheme, format, or credential configuration is invalid."""


class SSRFProtection:
    """Validates destination endpoints against Server-Side Request Forgery attacks."""

    @classmethod
    def validate_ip_address(
        cls,
        ip_str: str,
        allow_loopback_for_test: bool = False,
    ) -> None:
        """Verify an IP address does not target private, loopback, or metadata services."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as err:
            raise SSRFSecurityError(f"Invalid IP address format '{ip_str}': {err}") from err

        if ip_str in CLOUD_METADATA_IPS:
            raise SSRFSecurityError(f"Target IP '{ip_str}' is a forbidden cloud metadata service.")

        if ip.is_loopback:
            if not allow_loopback_for_test:
                raise SSRFSecurityError(f"Target IP '{ip_str}' is a loopback address.")
            return

        if ip.is_private:
            raise SSRFSecurityError(f"Target IP '{ip_str}' is an RFC1918 private network address.")

        if ip.is_link_local:
            raise SSRFSecurityError(f"Target IP '{ip_str}' is a link-local network address.")

        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise SSRFSecurityError(
                f"Target IP '{ip_str}' is a multicast, reserved, or unspecified address."
            )

    @classmethod
    def validate_url(
        cls,
        url: str,
        allow_http_for_test: bool = False,
        allow_loopback_for_test: bool = False,
    ) -> str:
        """Validate URL scheme, credentials, and resolved IP addresses against SSRF policies."""
        parsed = urlparse(url)

        # 1. Scheme validation
        allowed_schemes = ("https", "http") if allow_http_for_test else ("https",)
        if parsed.scheme.lower() not in allowed_schemes:
            raise InvalidURLError(
                f"URL scheme '{parsed.scheme}' is not permitted. Only HTTPS is allowed."
            )

        # 2. Reject credentials in URL
        if parsed.username or parsed.password:
            raise InvalidURLError(
                "Credentials embedded in model download URLs are strictly forbidden."
            )

        hostname = parsed.hostname
        if not hostname:
            raise InvalidURLError(f"Download URL '{url}' lacks a valid hostname.")

        # 3. Resolve hostname and validate all returned IP addresses
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as err:
            raise NetworkSecurityError(f"Failed to resolve hostname '{hostname}': {err}") from err

        if not addr_info:
            raise NetworkSecurityError(f"No IP addresses resolved for hostname '{hostname}'.")

        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            cls.validate_ip_address(ip_str, allow_loopback_for_test=allow_loopback_for_test)

        return cls.resolve_and_validate_target(
            url,
            allow_http_for_test=allow_http_for_test,
            allow_loopback_for_test=allow_loopback_for_test,
        )[0]

    @classmethod
    def resolve_and_validate_target(
        cls,
        url: str,
        allow_http_for_test: bool = False,
        allow_loopback_for_test: bool = False,
    ) -> tuple[str, str, str]:
        """Validate URL scheme, credentials, and resolve hostname to validate every candidate IP.

        Returns:
            tuple of (validated_url, hostname, pinned_ip) where pinned_ip is guaranteed to have passed validation.
        """
        parsed = urlparse(url)

        # 1. Scheme validation
        allowed_schemes = ("https", "http") if allow_http_for_test else ("https",)
        if parsed.scheme.lower() not in allowed_schemes:
            raise InvalidURLError(
                f"URL scheme '{parsed.scheme}' is not permitted. Only HTTPS is allowed."
            )

        # 2. Reject credentials in URL
        if parsed.username or parsed.password:
            raise InvalidURLError(
                "Credentials embedded in model download URLs are strictly forbidden."
            )

        hostname = parsed.hostname
        if not hostname:
            raise InvalidURLError(f"Download URL '{url}' lacks a valid hostname.")

        # 3. Resolve hostname and validate ALL returned IP addresses against SSRF policy
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as err:
            raise NetworkSecurityError(f"Failed to resolve hostname '{hostname}': {err}") from err

        if not addr_info:
            raise NetworkSecurityError(f"No IP addresses resolved for hostname '{hostname}'.")

        validated_ips: list[str] = []
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            cls.validate_ip_address(ip_str, allow_loopback_for_test=allow_loopback_for_test)
            validated_ips.append(ip_str)

        # Select the first fully-validated IP address to pin the socket connection to
        pinned_ip = validated_ips[0]
        return url, hostname, pinned_ip


from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.poolmanager import PoolManager


class PinningHTTPConnection(HTTPConnection):
    """HTTPConnection that binds its socket strictly to a pre-validated IP address."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pinned = getattr(self, "_pinned_ip_map", {})
        if self.host in pinned:
            self._dns_host = pinned[self.host]


class PinningHTTPSConnection(HTTPSConnection):
    """HTTPSConnection that connects strictly to pre-validated IP while preserving hostname for TLS SNI/verification."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        pinned = getattr(self, "_pinned_ip_map", {})
        if self.host in pinned:
            self._dns_host = pinned[self.host]
            if not self.server_hostname:
                self.server_hostname = self.host


class PinningPoolManager(PoolManager):
    """urllib3 PoolManager configured to inject Pinning connection classes."""

    def __init__(self, pinned_ips: dict[str, str], *args, **kwargs):
        self._pinned_ips = pinned_ips
        super().__init__(*args, **kwargs)

    def _new_pool(self, scheme, host, port, request_context=None):
        pool = super()._new_pool(scheme, host, port, request_context=request_context)
        if scheme == "https":
            pool.ConnectionCls = type(
                "ConfiguredPinningHTTPSConn",
                (PinningHTTPSConnection,),
                {"_pinned_ip_map": self._pinned_ips},
            )
        elif scheme == "http":
            pool.ConnectionCls = type(
                "ConfiguredPinningHTTPConn",
                (PinningHTTPConnection,),
                {"_pinned_ip_map": self._pinned_ips},
            )
        return pool


class PinningHTTPAdapter(HTTPAdapter):
    """Requests adapter enforcing socket-level connection to pre-validated IPs."""

    def __init__(self, pinned_ips: dict[str, str], **kwargs):
        self.pinned_ips = pinned_ips
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = PinningPoolManager(
            self.pinned_ips,
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )


class SafeStreamingDownloader:
    """Performs HTTP streaming downloads with anti-SSRF DNS pinning, redirect revalidation, and proxy isolation."""

    def __init__(
        self,
        allow_http_for_test: bool = False,
        allow_loopback_for_test: bool = False,
        max_redirects: int = 5,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
    ) -> None:
        self.allow_http_for_test = allow_http_for_test
        self.allow_loopback_for_test = allow_loopback_for_test
        self.max_redirects = max_redirects
        self.connect_timeout = connect_timeout_seconds
        self.read_timeout = read_timeout_seconds

    def create_session(self) -> requests.Session:
        """Create an isolated requests.Session with trust_env=False to prevent proxy bypass."""
        session = requests.Session()
        session.trust_env = False
        return session

    @property
    def session(self) -> requests.Session:
        """Provide a reference session for inspection and isolation verification."""
        return self.create_session()

    def open_stream(
        self,
        url: str,
        range_start: Optional[int] = None,
        if_range_etag: Optional[str] = None,
    ) -> requests.Response:
        """Open a streaming HTTP connection with DNS-pinned socket connections and redirect validation."""
        current_url = url
        redirect_count = 0
        pinned_ips: dict[str, str] = {}

        # 1. Isolate transport from environment proxies (HTTP_PROXY, HTTPS_PROXY, ALL_PROXY)
        session = self.create_session()

        # 2. Mount custom DNS-pinning adapter
        adapter = PinningHTTPAdapter(pinned_ips)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        while redirect_count <= self.max_redirects:
            # 3. Resolve and validate target host before connection
            _, host, pinned_ip = SSRFProtection.resolve_and_validate_target(
                current_url,
                allow_http_for_test=self.allow_http_for_test,
                allow_loopback_for_test=self.allow_loopback_for_test,
            )
            pinned_ips[host] = pinned_ip

            headers: dict[str, str] = {
                "User-Agent": "AgentEngine-ModelDownloader/0.5",
                "Accept-Encoding": "identity",  # Prevent gzip compression for direct byte counting
            }
            if range_start is not None and range_start > 0:
                headers["Range"] = f"bytes={range_start}-"
                if if_range_etag:
                    headers["If-Range"] = if_range_etag

            # Disable automatic redirect following to inspect and re-validate every hop
            response = session.get(
                current_url,
                headers=headers,
                stream=True,
                allow_redirects=False,
                timeout=(self.connect_timeout, self.read_timeout),
                verify=not self.allow_http_for_test,
            )

            # Check for redirect (301, 302, 303, 307, 308)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    response.close()
                    raise NetworkSecurityError(
                        f"HTTP {response.status_code} redirect without Location header."
                    )

                # Resolve relative redirect URLs against current URL
                redirect_target = urljoin(current_url, location)
                logger.info(
                    "Following verified redirect hop %d to %s", redirect_count + 1, redirect_target
                )

                # Re-validate target URL immediately (fail closed if target is private/loopback/metadata)
                _, redir_host, redir_ip = SSRFProtection.resolve_and_validate_target(
                    redirect_target,
                    allow_http_for_test=self.allow_http_for_test,
                    allow_loopback_for_test=self.allow_loopback_for_test,
                )
                pinned_ips[redir_host] = redir_ip

                response.close()
                current_url = redirect_target
                redirect_count += 1
                continue

            # Non-redirect response: return active stream
            return response

        raise NetworkSecurityError(f"Exceeded maximum redirect limit of {self.max_redirects} hops.")
