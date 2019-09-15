# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import json
import re
import traceback

from collections import OrderedDict

from charmhelpers.core.hookenv import (
    config,
    relation_ids,
    related_units,
    relation_get,
    log,
    DEBUG,
    ERROR,
)
from charmhelpers.contrib.openstack import context
from charmhelpers.contrib.hahelpers.cluster import (
    determine_api_port,
    determine_apache_port,
)
from charmhelpers.contrib.openstack.utils import (
    os_release,
    CompareOpenStackReleases,
)

VLAN = 'vlan'
VXLAN = 'vxlan'
GRE = 'gre'
FLAT = 'flat'
LOCAL = 'local'
OVERLAY_NET_TYPES = [VXLAN, GRE]
NON_OVERLAY_NET_TYPES = [VLAN, FLAT, LOCAL]
TENANT_NET_TYPES = [VXLAN, GRE, VLAN, FLAT, LOCAL]

EXTENSION_DRIVER_PORT_SECURITY = 'port_security'
EXTENSION_DRIVER_DNS = 'dns'
EXTENSION_DRIVER_DNS_DOMAIN_PORTS = 'dns_domain_ports'
EXTENSION_DRIVER_QOS = 'qos'

ETC_NEUTRON = '/etc/neutron'

NOTIFICATION_TOPICS = [
    'notifications',
]

# Domain name validation regex which is used to certify that
# the domain-name consists only of valid characters, is not
# longer than 63 characters in length for any name segment,
# and each segment does not begin or end with a hyphen.
DOMAIN_NAME_REGEX = re.compile(r'^(?!-)[A-Z\d-]{1,63}(?<!-)$',
                               re.IGNORECASE)


def get_l2population():
    plugin = config('neutron-plugin')
    return config('l2-population') if plugin == "ovs" else False


def _get_overlay_network_type():
    overlay_networks = config('overlay-network-type').split()
    for overlay_net in overlay_networks:
        if overlay_net not in OVERLAY_NET_TYPES:
            raise ValueError('Unsupported overlay-network-type %s'
                             % overlay_net)
    return overlay_networks


def get_overlay_network_type():
    return ','.join(_get_overlay_network_type())


def _get_tenant_network_types():
    default_tenant_network_type = config('default-tenant-network-type')
    tenant_network_types = _get_overlay_network_type()
    tenant_network_types.extend(NON_OVERLAY_NET_TYPES)
    if default_tenant_network_type:
        if (default_tenant_network_type in TENANT_NET_TYPES and
                default_tenant_network_type in tenant_network_types):
            tenant_network_types[:0] = [default_tenant_network_type]
        else:
            raise ValueError('Unsupported or unconfigured '
                             'default-tenant-network-type'
                             ' {}'.format(default_tenant_network_type))
    # Dedupe list but preserve order
    return list(OrderedDict.fromkeys(tenant_network_types))


def get_tenant_network_types():
    '''Get the configured tenant network types

    @return: comma delimited string of configured tenant
             network types.
    '''
    return ','.join(_get_tenant_network_types())


def get_l3ha():
    if config('enable-l3ha'):
        release = os_release('neutron-server')
        if CompareOpenStackReleases(release) < 'juno':
            log('Disabling L3 HA, enable-l3ha is not valid before Juno')
            return False
        if CompareOpenStackReleases(release) < 'newton' and get_l2population():
            log('Disabling L3 HA, l2-population must be disabled with L3 HA')
            return False
        return True
    else:
        return False


def get_dvr():
    if config('enable-dvr'):
        release = os_release('neutron-server')
        if CompareOpenStackReleases(release) < 'juno':
            log('Disabling DVR, enable-dvr is not valid before Juno')
            return False
        if CompareOpenStackReleases(release) == 'juno':
            if VXLAN not in config('overlay-network-type').split():
                log('Disabling DVR, enable-dvr requires the use of the vxlan '
                    'overlay network for OpenStack Juno')
                return False
        if get_l3ha() and CompareOpenStackReleases(release) < 'newton':
            log('Disabling DVR, enable-l3ha must be disabled with dvr')
            return False
        if not get_l2population():
            log('Disabling DVR, l2-population must be enabled to use dvr')
            return False
        return True
    else:
        return False


def get_dns_domain():
    if not config('enable-ml2-dns'):
        log('ML2 DNS Extensions are not enabled.', DEBUG)
        return ""

    dns_domain = config('dns-domain')
    if not dns_domain:
        log('No dns-domain has been configured', DEBUG)
        return dns_domain

    release = os_release('neutron-server')
    if CompareOpenStackReleases(release) < 'mitaka':
        log('Internal DNS resolution is not supported before Mitaka')
        return ""

    # Strip any trailing . at the end
    if dns_domain[-1] == '.':
        dns_domain = dns_domain[:-1]

    # Ensure that the dns name is only a valid name. Valid entries include
    # a-z, A-Z, 0-9, ., and -. No particular name may be longer than 63
    # characters, each part cannot begin/end with a -. Validate this here in
    # order to prevent other chaos which may prevent neutron services from
    # functioning properly.
    # Note: intentionally not validating the length of the domain name because
    # this is practically difficult to validate reasonably well.
    for level in dns_domain.split('.'):
        if not DOMAIN_NAME_REGEX.match(level):
            msg = "dns-domain '%s' is an invalid domain name." % dns_domain
            log(msg, ERROR)
            raise ValueError(msg)

    # Make sure it ends with a .
    dns_domain += '.'

    return dns_domain


def get_ml2_mechanism_drivers():
    """Build comma delimited list of mechanism drivers for use in Neutron
       ml2_conf.ini. Which drivers to enable are deduced from OpenStack
       release and charm configuration options.
    """
    mechanism_drivers = [
        'openvswitch',
    ]

    cmp_release = CompareOpenStackReleases(os_release('neutron-server'))
    if (cmp_release == 'kilo' or cmp_release >= 'mitaka'):
        mechanism_drivers.append('hyperv')

    if get_l2population():
        mechanism_drivers.append('l2population')

    if (config('enable-sriov') and cmp_release >= 'kilo'):
        mechanism_drivers.append('sriovnicswitch')
    return ','.join(mechanism_drivers)


def is_qos_requested_and_valid():
    """Check whether QoS should be enabled by checking whether it has been
       requested and, if it has, is it supported in the current configuration
    """

    if config('enable-qos'):
        if CompareOpenStackReleases(os_release('neutron-server')) < 'mitaka':
            msg = ("The enable-qos option is only supported on mitaka or "
                   "later")
            log(msg, ERROR)
            return False
        else:
            return True
    else:
        return False


def is_nsg_logging_enabled():
    """
    Check, if Neutron security groups logging should be enabled.
    Works only on >=Queens and with OVS native firewall driver:
    https://docs.openstack.org/neutron/queens/admin/config-logging.html
    """
    if config('enable-security-group-logging'):
        if config('neutron-plugin') != 'ovs':
            msg = ("Disabling NSG logging; implementation only exists "
                   "for the OVS ML2 driver")
            log(msg, ERROR)
            return False

        if CompareOpenStackReleases(os_release('neutron-server')) < 'queens':
            msg = ("The enable-security-group-logging option is only "
                   "supported on Queens or later")
            log(msg, ERROR)
            return False

        return True

    return False


def is_nfg_logging_enabled():
    """
    Check if Neutron firewall groups logging should be enabled.
    """
    if config('enable-firewall-group-logging'):

        if CompareOpenStackReleases(os_release('neutron-server')) < 'stein':
            log("The logging option is only supported on Stein or later",
                ERROR)
            return False

        return True

    return False


def is_vlan_trunking_requested_and_valid():
    """Check whether VLAN trunking should be enabled by checking whether
       it has been requested and, if it has, is it supported in the current
       configuration.
    """

    if config('enable-vlan-trunking'):
        if VLAN not in _get_tenant_network_types():
            msg = ("Disabling vlan-trunking, the vlan network type must be "
                   "enabled to use vlan-trunking")
            log(msg, ERROR)
            return False

        if config('neutron-plugin') != 'ovs':
            msg = ("Disabling vlan-trunking, implementation only exists "
                   "for the OVS plugin")
            log(msg, ERROR)
            return False

        if CompareOpenStackReleases(os_release('neutron-server')) < 'newton':
            msg = ("The vlan-trunking option is only supported on newton or "
                   "later")
            log(msg, ERROR)
            return False

        return True
    else:
        return False


class ApacheSSLContext(context.ApacheSSLContext):

    interfaces = ['https']
    external_ports = []
    service_namespace = 'neutron'

    def __call__(self):
        # late import to work around circular dependency
        from neutron_api_utils import determine_ports
        self.external_ports = determine_ports()
        return super(ApacheSSLContext, self).__call__()


class IdentityServiceContext(context.IdentityServiceContext):

    def __call__(self):
        ctxt = super(IdentityServiceContext, self).__call__()
        if not ctxt:
            return
        ctxt['region'] = config('region')
        return ctxt


class NeutronCCContext(context.NeutronContext):
    interfaces = []

    @property
    def network_manager(self):
        return 'neutron'

    @property
    def plugin(self):
        return config('neutron-plugin')

    @property
    def neutron_security_groups(self):
        return config('neutron-security-groups')

    @property
    def neutron_l2_population(self):
        return get_l2population()

    @property
    def neutron_tenant_network_types(self):
        return get_tenant_network_types()

    @property
    def neutron_overlay_network_type(self):
        return get_overlay_network_type()

    @property
    def neutron_dvr(self):
        return get_dvr()

    @property
    def neutron_l3ha(self):
        return get_l3ha()

    # Do not need the plugin agent installed on the api server
    def _ensure_packages(self):
        pass

    # Do not need the flag on the api server
    def _save_flag_file(self):
        pass

    def get_neutron_api_rel_settings(self):
        settings = {}
        for rid in relation_ids('neutron-api'):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                cell_type = rdata.get('cell_type')
                settings['nova_url'] = rdata.get('nova_url')
                settings['restart_trigger'] = rdata.get('restart_trigger')
                # If there are multiple nova-cloud-controllers joined to this
                # service in a cell deployment then ignore the non-api cell
                # ones
                if cell_type and not cell_type == "api":
                    continue

                if settings['nova_url']:
                    return settings

        return settings

    def __call__(self):
        from neutron_api_utils import api_port
        ctxt = super(NeutronCCContext, self).__call__()
        if config('neutron-plugin') == 'nsx':
            ctxt['nsx_username'] = config('nsx-username')
            ctxt['nsx_password'] = config('nsx-password')
            ctxt['nsx_tz_uuid'] = config('nsx-tz-uuid')
            ctxt['nsx_l3_uuid'] = config('nsx-l3-uuid')
            if 'nsx-controllers' in config():
                ctxt['nsx_controllers'] = \
                    ','.join(config('nsx-controllers').split())
                ctxt['nsx_controllers_list'] = \
                    config('nsx-controllers').split()
        if config('neutron-plugin') == 'plumgrid':
            ctxt['pg_username'] = config('plumgrid-username')
            ctxt['pg_password'] = config('plumgrid-password')
            ctxt['virtual_ip'] = config('plumgrid-virtual-ip')
        elif config('neutron-plugin') == 'midonet':
            ctxt.update(MidonetContext()())
            identity_context = IdentityServiceContext(service='neutron',
                                                      service_user='neutron')()
            if identity_context is not None:
                ctxt.update(identity_context)
        ctxt['l2_population'] = self.neutron_l2_population
        ctxt['enable_dvr'] = self.neutron_dvr
        ctxt['l3_ha'] = self.neutron_l3ha
        if self.neutron_l3ha:
            max_agents = config('max-l3-agents-per-router')
            min_agents = config('min-l3-agents-per-router')
            if max_agents < min_agents:
                raise ValueError("max-l3-agents-per-router ({}) must be >= "
                                 "min-l3-agents-per-router "
                                 "({})".format(max_agents, min_agents))

            ctxt['max_l3_agents_per_router'] = max_agents
            ctxt['min_l3_agents_per_router'] = min_agents

        ctxt['allow_automatic_l3agent_failover'] = \
            config('allow-automatic-l3agent-failover')
        ctxt['allow_automatic_dhcp_failover'] = \
            config('allow-automatic-dhcp-failover')

        ctxt['dhcp_agents_per_network'] = config('dhcp-agents-per-network')
        ctxt['tenant_network_types'] = self.neutron_tenant_network_types
        ctxt['overlay_network_type'] = self.neutron_overlay_network_type
        ctxt['external_network'] = config('neutron-external-network')
        release = os_release('neutron-server')
        cmp_release = CompareOpenStackReleases(release)
        if config('neutron-plugin') == 'vsp' and cmp_release < 'newton':
            _config = config()
            for k, v in _config.items():
                if k.startswith('vsd'):
                    ctxt[k.replace('-', '_')] = v
            for rid in relation_ids('vsd-rest-api'):
                for unit in related_units(rid):
                    rdata = relation_get(rid=rid, unit=unit)
                    vsd_ip = rdata.get('vsd-ip-address')
                    if cmp_release >= 'kilo':
                        cms_id_value = rdata.get('nuage-cms-id')
                        log('relation data:cms_id required for'
                            ' nuage plugin: {}'.format(cms_id_value))
                        if cms_id_value is not None:
                            ctxt['vsd_cms_id'] = cms_id_value
                    log('relation data:vsd-ip-address: {}'.format(vsd_ip))
                    if vsd_ip is not None:
                        ctxt['vsd_server'] = '{}:8443'.format(vsd_ip)
            if 'vsd_server' not in ctxt:
                ctxt['vsd_server'] = '1.1.1.1:8443'
        ctxt['verbose'] = config('verbose')
        ctxt['debug'] = config('debug')
        ctxt['neutron_bind_port'] = \
            determine_api_port(api_port('neutron-server'),
                               singlenode_mode=True)
        ctxt['quota_security_group'] = config('quota-security-group')
        ctxt['quota_security_group_rule'] = \
            config('quota-security-group-rule')
        ctxt['quota_network'] = config('quota-network')
        ctxt['quota_subnet'] = config('quota-subnet')
        ctxt['quota_port'] = config('quota-port')
        ctxt['quota_vip'] = config('quota-vip')
        ctxt['quota_pool'] = config('quota-pool')
        ctxt['quota_member'] = config('quota-member')
        ctxt['quota_health_monitors'] = config('quota-health-monitors')
        ctxt['quota_router'] = config('quota-router')
        ctxt['quota_floatingip'] = config('quota-floatingip')

        n_api_settings = self.get_neutron_api_rel_settings()
        if n_api_settings:
            ctxt.update(n_api_settings)

        flat_providers = config('flat-network-providers')
        if flat_providers:
            ctxt['network_providers'] = ','.join(flat_providers.split())

        vlan_ranges = config('vlan-ranges')
        if vlan_ranges:
            ctxt['vlan_ranges'] = ','.join(vlan_ranges.split())

        vni_ranges = config('vni-ranges')
        if vni_ranges:
            ctxt['vni_ranges'] = ','.join(vni_ranges.split())

        enable_dns_extension_driver = False

        dns_domain = get_dns_domain()
        if dns_domain:
            enable_dns_extension_driver = True
            ctxt['dns_domain'] = dns_domain

        if cmp_release >= 'mitaka':
            for rid in relation_ids('external-dns'):
                if related_units(rid):
                    enable_dns_extension_driver = True

            # AZAwareWeightScheduler inherits from WeightScheduler and is
            # available as of mitaka
            ctxt['network_scheduler_driver'] = (
                'neutron.scheduler.dhcp_agent_scheduler.AZAwareWeightScheduler'
            )
            ctxt['dhcp_load_type'] = config('dhcp-load-type')

        extension_drivers = []
        if config('enable-ml2-port-security'):
            extension_drivers.append(EXTENSION_DRIVER_PORT_SECURITY)
        if enable_dns_extension_driver:
            if cmp_release < 'queens':
                extension_drivers.append(EXTENSION_DRIVER_DNS)
            else:
                extension_drivers.append(EXTENSION_DRIVER_DNS_DOMAIN_PORTS)

        if is_qos_requested_and_valid():
            extension_drivers.append(EXTENSION_DRIVER_QOS)

        if extension_drivers:
            ctxt['extension_drivers'] = ','.join(extension_drivers)

        ctxt['enable_sriov'] = config('enable-sriov')

        if cmp_release >= 'mitaka':
            if config('global-physnet-mtu'):
                ctxt['global_physnet_mtu'] = config('global-physnet-mtu')
                if config('path-mtu'):
                    ctxt['path_mtu'] = config('path-mtu')
                else:
                    ctxt['path_mtu'] = config('global-physnet-mtu')
                physical_network_mtus = config('physical-network-mtus')
                if physical_network_mtus:
                    ctxt['physical_network_mtus'] = ','.join(
                        physical_network_mtus.split())

        if 'kilo' <= cmp_release <= 'mitaka':
            pci_vendor_devs = config('supported-pci-vendor-devs')
            if pci_vendor_devs:
                ctxt['supported_pci_vendor_devs'] = \
                    ','.join(pci_vendor_devs.split())

        ctxt['mechanism_drivers'] = get_ml2_mechanism_drivers()

        n_load_balancer_settings = NeutronLoadBalancerContext()()
        if n_load_balancer_settings:
            ctxt.update(n_load_balancer_settings)

        if config('neutron-plugin') in ['ovs', 'ml2', 'Calico']:
            ctxt['service_plugins'] = []
            service_plugins = {
                'icehouse': [
                    ('neutron.services.l3_router.l3_router_plugin.'
                     'L3RouterPlugin'),
                    'neutron.services.firewall.fwaas_plugin.FirewallPlugin',
                    'neutron.services.loadbalancer.plugin.LoadBalancerPlugin',
                    'neutron.services.vpn.plugin.VPNDriverPlugin',
                    ('neutron.services.metering.metering_plugin.'
                     'MeteringPlugin')],
                'juno': [
                    ('neutron.services.l3_router.l3_router_plugin.'
                     'L3RouterPlugin'),
                    'neutron.services.firewall.fwaas_plugin.FirewallPlugin',
                    'neutron.services.loadbalancer.plugin.LoadBalancerPlugin',
                    'neutron.services.vpn.plugin.VPNDriverPlugin',
                    ('neutron.services.metering.metering_plugin.'
                     'MeteringPlugin')],
                'kilo': ['router', 'firewall', 'lbaas', 'vpnaas', 'metering'],
                'liberty': ['router', 'firewall', 'lbaas', 'vpnaas',
                            'metering'],
                'mitaka': ['router', 'firewall', 'lbaas', 'vpnaas',
                           'metering'],
                'newton': ['router', 'firewall', 'vpnaas', 'metering',
                           ('neutron_lbaas.services.loadbalancer.plugin.'
                            'LoadBalancerPluginv2')],
                'ocata': ['router', 'firewall', 'vpnaas', 'metering',
                          ('neutron_lbaas.services.loadbalancer.plugin.'
                           'LoadBalancerPluginv2'), 'segments',
                          ('neutron_dynamic_routing.'
                           'services.bgp.bgp_plugin.BgpPlugin')],
                'pike': ['router', 'firewall', 'metering', 'segments',
                         ('neutron_lbaas.services.loadbalancer.plugin.'
                          'LoadBalancerPluginv2'),
                         ('neutron_dynamic_routing.'
                          'services.bgp.bgp_plugin.BgpPlugin')],
                'queens': ['router', 'firewall', 'metering', 'segments',
                           ('neutron_lbaas.services.loadbalancer.plugin.'
                            'LoadBalancerPluginv2'),
                           ('neutron_dynamic_routing.'
                            'services.bgp.bgp_plugin.BgpPlugin')],
                'rocky': ['router', 'firewall', 'metering', 'segments',
                          ('neutron_dynamic_routing.'
                           'services.bgp.bgp_plugin.BgpPlugin')],
                'stein': ['router', 'firewall_v2', 'metering', 'segments',
                          ('neutron_dynamic_routing.'
                           'services.bgp.bgp_plugin.BgpPlugin')],
            }
            if cmp_release >= 'rocky':
                if ctxt.get('load_balancer_name', None):
                    # TODO(fnordahl): Remove when ``neutron_lbaas`` is retired
                    service_plugins[release].append('lbaasv2-proxy')
                else:
                    # TODO(fnordahl): Remove fall-back in next charm release
                    service_plugins[release].append('lbaasv2')

            if cmp_release >= 'stein':
                ctxt['firewall_v2'] = True

            ctxt['service_plugins'] = service_plugins.get(
                release, service_plugins['stein'])

            if is_nsg_logging_enabled() or is_nfg_logging_enabled():
                ctxt['service_plugins'].append('log')

            if is_qos_requested_and_valid():
                ctxt['service_plugins'].append('qos')

            if is_vlan_trunking_requested_and_valid():
                ctxt['service_plugins'].append('trunk')

            ctxt['service_plugins'] = ','.join(ctxt['service_plugins'])

        if config('neutron-plugin') == 'aci':
            identity_context = IdentityServiceContext(service='neutron',
                                                      service_user='neutron')()
            if identity_context is not None:
                ctxt.update(identity_context)
            ctxt.update(CiscoAciContext()())

        return ctxt


class HAProxyContext(context.HAProxyContext):
    interfaces = ['ceph']

    def __call__(self):
        '''
        Extends the main charmhelpers HAProxyContext with a port mapping
        specific to this charm.
        Also used to extend nova.conf context with correct api_listening_ports
        '''
        from neutron_api_utils import api_port
        ctxt = super(HAProxyContext, self).__call__()

        # Apache ports
        a_neutron_api = determine_apache_port(api_port('neutron-server'),
                                              singlenode_mode=True)

        port_mapping = {
            'neutron-server': [
                api_port('neutron-server'), a_neutron_api]
        }

        ctxt['neutron_bind_port'] = determine_api_port(
            api_port('neutron-server'),
            singlenode_mode=True,
        )

        # for haproxy.conf
        ctxt['service_ports'] = port_mapping
        return ctxt


class EtcdContext(context.OSContextGenerator):
    interfaces = ['etcd-proxy']

    def __call__(self):
        ctxt = {'cluster': ''}
        cluster_string = ''

        if not config('neutron-plugin') == 'Calico':
            return ctxt

        for rid in relation_ids('etcd-proxy'):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                cluster_string = rdata.get('cluster')
                if cluster_string:
                    break

        ctxt['cluster'] = cluster_string

        return ctxt


class NeutronApiSDNContext(context.SubordinateConfigContext):
    interfaces = 'neutron-plugin-api-subordinate'

    def __init__(self):
        super(NeutronApiSDNContext, self).__init__(
            interface='neutron-plugin-api-subordinate',
            service='neutron-api',
            config_file='/etc/neutron/neutron.conf')

    def __call__(self):
        ctxt = super(NeutronApiSDNContext, self).__call__()
        defaults = {
            'core-plugin': {
                'templ_key': 'core_plugin',
                'value': 'neutron.plugins.ml2.plugin.Ml2Plugin',
            },
            'neutron-plugin-config': {
                'templ_key': 'neutron_plugin_config',
                'value': '/etc/neutron/plugins/ml2/ml2_conf.ini',
            },
            'service-plugins': {
                'templ_key': 'service_plugins',
                'value': 'router,firewall,lbaas,vpnaas,metering',
            },
            'restart-trigger': {
                'templ_key': 'restart_trigger',
                'value': '',
            },
            'quota-driver': {
                'templ_key': 'quota_driver',
                'value': '',
            },
            'api-extensions-path': {
                'templ_key': 'api_extensions_path',
                'value': '',
            },
        }
        for rid in relation_ids('neutron-plugin-api-subordinate'):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                plugin = rdata.get('neutron-plugin')
                if not plugin:
                    continue
                ctxt['neutron_plugin'] = plugin
                for key in defaults.keys():
                    remote_value = rdata.get(key)
                    ctxt_key = defaults[key]['templ_key']
                    if remote_value:
                        ctxt[ctxt_key] = remote_value
                    else:
                        ctxt[ctxt_key] = defaults[key]['value']
                return ctxt
        return ctxt


class NeutronApiSDNConfigFileContext(context.OSContextGenerator):
    interfaces = ['neutron-plugin-api-subordinate']

    def __call__(self):
        for rid in relation_ids('neutron-plugin-api-subordinate'):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                neutron_server_plugin_conf = rdata.get('neutron-plugin-config')
                if neutron_server_plugin_conf:
                    return {'config': neutron_server_plugin_conf}
        return {'config': '/etc/neutron/plugins/ml2/ml2_conf.ini'}


class NeutronApiApiPasteContext(context.OSContextGenerator):
    interfaces = ['neutron-plugin-api-subordinate']

    def __validate_middleware(self, middleware):
        '''
        Accepts a list of dicts of the following format:
            {
                'type': 'middleware_type',
                'name': 'middleware_name',
                'config': {
                    option_1: value_1,
                    # ...
                    option_n: value_n
                }
        This validator was meant to be minimalistic - PasteDeploy's
        validator will take care of the rest while our purpose here
        is mainly config rendering - not imposing additional validation
        logic which does not belong here.
        '''
        # types taken from PasteDeploy's wsgi loader
        VALID_TYPES = ['filter', 'filter-app',
                       'app', 'application',
                       'composite', 'composit', 'pipeline']

        def types_valid(t, n, c):
            return all((type(t) is str,
                       type(n) is str,
                       type(c is dict)))

        def mtype_valid(t):
            return t in VALID_TYPES

        for m in middleware:
            t, n, c = [m.get(v) for v in ['type', 'name', 'config']]
            # note that dict has to be non-empty
            if not types_valid(t, n, c):
                    raise ValueError('Extra middleware key type(s) are'
                                     ' invalid: {}'.format(repr(m)))
            if not mtype_valid(t):
                    raise ValueError('Extra middleware type key is not'
                                     ' a valid PasteDeploy middleware '
                                     'type {}'.format(repr(t)))
            if not c:
                raise ValueError('Extra middleware config dictionary'
                                 ' is empty')

    def __process_unit(self, rid, unit):
        rdata = relation_get(rid=rid, unit=unit)
        # update extra middleware for all possible plugins
        rdata_middleware = rdata.get('extra_middleware')
        if rdata_middleware:
            try:
                middleware = ast.literal_eval(rdata_middleware)
            except:
                import traceback
                log(traceback.format_exc())
                raise ValueError('Invalid extra middleware data'
                                 ' - check the subordinate charm')
            if middleware:
                return middleware
            else:
                log('extra_middleware specified but not'
                    'populated by unit {}, '
                    'relation: {}, value: {}'.format(
                        unit, rid, repr(middleware)))
                raise ValueError('Invalid extra middleware'
                                 'specified by a subordinate')
        # no extra middleware
        return list()

    def __call__(self):
        extra_middleware = []
        for rid in relation_ids('neutron-plugin-api-subordinate'):
            for unit in related_units(rid):
                extra_middleware.extend(self.__process_unit(rid, unit))
        self.__validate_middleware(extra_middleware)
        return {'extra_middleware': extra_middleware}\
            if extra_middleware else {}


class NeutronLoadBalancerContext(context.OSContextGenerator):
    interfaces = ['neutron-load-balancer']

    def __call__(self):
        ctxt = {}
        for rid in relation_ids('neutron-load-balancer'):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                try:
                    ctxt['load_balancer_name'] = json.loads(
                        rdata.get('name'))
                    ctxt['load_balancer_base_url'] = json.loads(
                        rdata.get('base_url'))
                except TypeError:
                    pass
                except json.decoder.JSONDecodeError:
                    log(traceback.format_exc())
                    raise ValueError('Invalid load balancer data'
                                     ' - check the related charm')
                if self.context_complete(ctxt):
                    return ctxt
        return {}


class MidonetContext(context.OSContextGenerator):

    def __init__(self, rel_name='midonet'):
        self.rel_name = rel_name
        self.interfaces = [rel_name]

    def __call__(self):
        for rid in relation_ids(self.rel_name):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                ctxt = {
                    'midonet_api_ip': rdata.get('host'),
                    'midonet_api_port': rdata.get('port'),
                }
                if self.context_complete(ctxt):
                    return ctxt
        return {}


class NeutronAMQPContext(context.AMQPContext):
    '''AMQP context with Neutron API sauce'''

    def __init__(self):
        super(NeutronAMQPContext, self).__init__(ssl_dir=ETC_NEUTRON)

    def __call__(self):
        context = super(NeutronAMQPContext, self).__call__()
        # TODO (dparv) The class to be removed in next charm release
        # and from BASE_RESOURCE_MAP neutron_api_utils.py as well
        if not context:
            return context
        context['notification_topics'] = ','.join(NOTIFICATION_TOPICS)
        return context


class DesignateContext(context.OSContextGenerator):
    interfaces = ['external-dns']

    def __call__(self):
        ctxt = {}
        for rid in relation_ids('external-dns'):
            if related_units(rid):
                for unit in related_units(rid):
                    rdata = relation_get(rid=rid, unit=unit)
                    ctxt['designate_endpoint'] = rdata.get('endpoint')
        if ctxt.get('designate_endpoint') is not None:
            ctxt['enable_designate'] = True
            allow_reverse_dns_lookup = config('reverse-dns-lookup')
            ctxt['allow_reverse_dns_lookup'] = allow_reverse_dns_lookup
            if allow_reverse_dns_lookup:
                ctxt['ipv4_ptr_zone_prefix_size'] = (
                    config('ipv4-ptr-zone-prefix-size'))
                ctxt['ipv6_ptr_zone_prefix_size'] = (
                    config('ipv6-ptr-zone-prefix-size'))
        return ctxt


class NeutronInfobloxContext(context.OSContextGenerator):
    '''Infoblox IPAM context for Neutron API'''
    interfaces = ['infoblox-neutron']

    def __call__(self):
        ctxt = {}
        rdata = {}
        for rid in relation_ids('infoblox-neutron'):
            if related_units(rid) and not rdata:
                for unit in related_units(rid):
                    rdata = relation_get(rid=rid, unit=unit)
                    ctxt['cloud_data_center_id'] = rdata.get('dc_id')
                    break
        if ctxt.get('cloud_data_center_id') is not None:
            if not self.check_requirements(rdata):
                log('Missing Infoblox connection information, passing.')
                return {}
            ctxt['enable_infoblox'] = True
            ctxt['cloud_data_center_id'] = rdata.get('dc_id')
            ctxt['grid_master_host'] = rdata.get('grid_master_host')
            ctxt['grid_master_name'] = rdata.get('grid_master_name')
            ctxt['infoblox_admin_user_name'] = rdata.get('admin_user_name')
            ctxt['infoblox_admin_password'] = rdata.get('admin_password')
            # the next three values are non-critical and may accept defaults
            ctxt['wapi_version'] = rdata.get('wapi_version', '2.3')
            ctxt['wapi_max_results'] = rdata.get('wapi_max_results', '-50000')
            ctxt['wapi_paging'] = rdata.get('wapi_paging', True)
        return ctxt

    def check_requirements(self, rdata):
        required = [
            'grid_master_name',
            'grid_master_host',
            'admin_user_name',
            'admin_password',
        ]
        return len(set(p for p, v in rdata.items() if v).
                   intersection(required)) == len(required)


class CiscoAciContext(context.OSContextGenerator):
    def __init__(self, rel_name='neutron-plugin-api-subordinate'):
        self.rel_name = rel_name
        self.interfaces = [rel_name]

    def __call__(self):
        for rid in relation_ids(self.rel_name):
            for unit in related_units(rid):
                rdata = relation_get(rid=rid, unit=unit)
                plugin = rdata.get('neutron_plugin')
                if str(plugin) == "aci":
                    ctxt = {}
                    for k in rdata.keys():
                        ctxt[k] = rdata.get(k)
                    if self.context_complete(ctxt):
                        return ctxt
        return {}
