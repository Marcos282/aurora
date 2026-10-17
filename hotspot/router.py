import ipaddress
import json
import ssl
import subprocess

import httpx
from django.conf import settings

from .security import RouterUnavailable, decrypt


OFFLINE = 'MikroTik desconectado — Não foi possível consultar os usuários.'


def verify_tunnel(address):
    try:
        ip = ipaddress.ip_address(address)
        networks = [ipaddress.ip_network(n) for n in settings.NOVAINFO_WIREGUARD_NETWORKS]
        if not ip.is_private or ip.is_loopback or ip.is_link_local or not any(ip in n for n in networks):
            raise ValueError
        result = subprocess.run(['ip', '-j', 'route', 'get', str(ip)], check=True, capture_output=True, text=True, timeout=3)
        routes = json.loads(result.stdout)
        if not routes or routes[0].get('dev') != settings.NOVAINFO_WIREGUARD_INTERFACE:
            raise ValueError
        interface = subprocess.run(['ip', '-d', '-j', 'link', 'show', 'dev', settings.NOVAINFO_WIREGUARD_INTERFACE], check=True, capture_output=True, text=True, timeout=3)
        links = json.loads(interface.stdout)
        if not links or links[0].get('linkinfo', {}).get('info_kind') != 'wireguard':
            raise ValueError
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        raise RouterUnavailable(OFFLINE) from None


class RouterClient:
    def __init__(self, router):
        self.router = router

    def request(self, method, path, **kwargs):
        if not self.router.enabled:
            raise RouterUnavailable(OFFLINE)
        verify_tunnel(self.router.tunnel_ip)
        try:
            context = ssl.create_default_context(cafile=settings.NOVAINFO_ROUTER_CA or None)
            with httpx.Client(
                base_url=f'https://{self.router.tunnel_ip}:{self.router.https_port}/rest/',
                auth=(self.router.api_user, decrypt(self.router.encrypted_password)),
                verify=context, timeout=5, trust_env=False, follow_redirects=False,
            ) as client:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, OSError, ValueError):
            # Never send router bodies, credentials, IPs or exceptions to the browser/log.
            raise RouterUnavailable(OFFLINE) from None

    def probe(self):
        result = self.request('GET', 'system/resource', params={'.proplist': 'uptime'})
        if not isinstance(result, list) or not result or not all(isinstance(row, dict) and row.get('uptime') for row in result):
            raise RouterUnavailable(OFFLINE)

    def online(self):
        rows = self.request('GET', 'ip/hotspot/active', params={'.proplist': 'user,address,uptime,server', 'server': self.router.hotspot_server})
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RouterUnavailable(OFFLINE)
        return [{'username': str(row.get('user', ''))[:100], 'ip': str(row.get('address', ''))[:50], 'uptime': str(row.get('uptime', ''))[:60]} for row in rows if row.get('server') == self.router.hotspot_server]

    def create_user(self, grant, password):
        if grant.duration_seconds not in (3600, 10800, 21600):
            raise RouterUnavailable('Plano de acesso inválido.')
        hours = grant.duration_seconds // 3600
        duration = f'{hours}h'
        profile = f'ni-{grant.tenant_id.hex}-{grant.devices}-{duration}'
        expected = {'shared-users': str(grant.devices), 'session-timeout': duration, 'add-mac-cookie': 'no'}
        profiles = self.request('GET', 'ip/hotspot/user/profile', params={'name': profile})
        if not isinstance(profiles, list) or any(not isinstance(row, dict) for row in profiles):
            raise RouterUnavailable(OFFLINE)
        exact = [row for row in profiles if row.get('name') == profile]
        if exact:
            # Do not silently reuse an existing profile with weaker limits.
            if any(str(exact[0].get(k)) not in (v, f'{hours:02}:00:00' if k == 'session-timeout' else v) for k, v in expected.items()):
                raise RouterUnavailable('Perfil do Hotspot precisa de revisão técnica.')
        else:
            self.request('PUT', 'ip/hotspot/user/profile', json={'name': profile, **expected})
        result = self.request('PUT', 'ip/hotspot/user', json={
            'name': grant.username, 'password': password, 'profile': profile,
            'server': self.router.hotspot_server, 'limit-uptime': duration,
            'comment': f'Nova Info {grant.request_id}',
        })
        if not isinstance(result, dict) or not result.get('.id'):
            raise RouterUnavailable('Confirmação de criação indisponível.')
        return str(result['.id'])
