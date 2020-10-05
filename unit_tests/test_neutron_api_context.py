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

import json

from mock import MagicMock, patch

import neutron_api_context as context
import charmhelpers

from test_utils import CharmTestCase

TO_PATCH = [
    'config',
    'determine_api_port',
    'determine_apache_port',
    'log',
    'os_release',
    'relation_get',
    'relation_ids',
    'related_units',
]


class GeneralTests(CharmTestCase):
    def setUp(self):
        super(GeneralTests, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get

    def test_l2population(self):
        self.test_config.set('l2-population', True)
        self.test_config.set('neutron-plugin', 'ovs')
        self.assertEqual(context.get_l2population(), True)

    def test_l2population_nonovs(self):
        self.test_config.set('l2-population', True)
        self.test_config.set('neutron-plugin', 'nsx')
        self.assertEqual(context.get_l2population(), False)

    def test_get_tenant_network_types(self):
        self.test_config.set('overlay-network-type', 'gre')
        self.assertEqual(
            context._get_tenant_network_types(),
            ['gre', 'vlan', 'flat', 'local'])

    def test_get_tenant_network_types_multi(self):
        self.test_config.set('overlay-network-type', 'gre vxlan')
        self.assertEqual(
            context._get_tenant_network_types(),
            ['gre', 'vxlan', 'vlan', 'flat', 'local'])

    def test_get_tenant_network_types_unsupported(self):
        self.test_config.set('overlay-network-type', 'tokenring')
        with self.assertRaises(ValueError):
            context._get_tenant_network_types()

    def test_get_tenant_network_types_default(self):
        self.test_config.set('overlay-network-type', 'gre vxlan')
        self.test_config.set('default-tenant-network-type', 'vxlan')
        self.assertEqual(
            context._get_tenant_network_types(),
            ['vxlan', 'gre', 'vlan', 'flat', 'local'])

    def test_get_tenant_network_types_default_dup(self):
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('default-tenant-network-type', 'vlan')
        self.assertEqual(
            context._get_tenant_network_types(),
            ['vlan', 'gre', 'flat', 'local'])

    def test_get_tenant_network_types_empty(self):
        self.test_config.set('overlay-network-type', '')
        self.test_config.set('default-tenant-network-type', 'vlan')
        self.assertEqual(
            context._get_tenant_network_types(),
            ['vlan', 'flat', 'local'])

    def test_get_tenant_network_types_unsupported_default(self):
        self.test_config.set('overlay-network-type', '')
        self.test_config.set('default-tenant-network-type', 'whizzy')
        with self.assertRaises(ValueError):
            context._get_tenant_network_types()

    def test_get_tenant_network_types_unconfigured_default(self):
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('default-tenant-network-type', 'vxlan')
        with self.assertRaises(ValueError):
            context._get_tenant_network_types()

    def test_get_l3ha(self):
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', False)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_l3ha(), True)

    def test_get_l3ha_prejuno(self):
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', False)
        self.os_release.return_value = 'icehouse'
        self.assertEqual(context.get_l3ha(), False)

    def test_get_l3ha_l2pop(self):
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_l3ha(), False)

    def test_get_dvr(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_dvr(), True)

    def test_get_dvr_explicit_off(self):
        self.test_config.set('enable-dvr', False)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_dvr(), False)

    def test_get_dvr_prejuno(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'icehouse'
        self.assertEqual(context.get_dvr(), False)

    def test_get_dvr_gre(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_dvr(), False)

    def test_get_dvr_gre_kilo(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'kilo'
        self.assertEqual(context.get_dvr(), True)

    def test_get_dvr_vxlan_kilo(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', True)
        self.os_release.return_value = 'kilo'
        self.assertEqual(context.get_dvr(), True)

    def test_get_dvr_l3ha_on(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', False)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_dvr(), False)

    def test_get_dvr_l2pop(self):
        self.test_config.set('enable-dvr', True)
        self.test_config.set('enable-l3ha', False)
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', False)
        self.os_release.return_value = 'juno'
        self.assertEqual(context.get_dvr(), False)

    def test_get_dns_domain(self):
        self.test_config.set('dns-domain', 'example.org.')
        self.test_config.set('enable-ml2-dns', True)
        self.os_release.return_value = 'mitaka'
        self.assertEqual(context.get_dns_domain(), 'example.org.')

    def test_get_dns_domain_bad_values(self):
        self.os_release.return_value = 'mitaka'
        self.test_config.set('enable-ml2-dns', True)
        bad_values = ['example@foo.org',
                      'exclamation!marks.notwelcom.ed',
                      '%s.way.too.long' % ('x' * 64),
                      '-hyphen.in.front',
                      'hypen-.in.back',
                      'no_.under_scor.es',
                      ]

        for value in bad_values:
            self.test_config.set('dns-domain', value)
            self.assertRaises(ValueError, context.get_dns_domain)

    def test_get_ml2_mechanism_drivers(self):
        self.os_release.return_value = 'mitaka'
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,hyperv,l2population')

    def test_get_ml2_mechanism_drivers_kilo(self):
        self.os_release.return_value = 'kilo'
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,hyperv,l2population')

    def test_get_ml2_mechanism_drivers_liberty(self):
        self.os_release.return_value = 'liberty'
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,l2population')

    def test_get_ml2_mechanism_drivers_no_l2pop(self):
        self.os_release.return_value = 'mitaka'
        self.test_config.set('l2-population', False)
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,hyperv')

    def test_get_ml2_mechanism_drivers_sriov(self):
        self.os_release.return_value = 'mitaka'
        self.test_config.set('enable-sriov', True)
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,hyperv,l2population,sriovnicswitch')

    def test_get_ml2_mechanism_drivers_no_l2pop_sriov(self):
        self.os_release.return_value = 'mitaka'
        self.test_config.set('enable-sriov', True)
        self.test_config.set('l2-population', False)
        self.assertEqual(context.get_ml2_mechanism_drivers(),
                         'openvswitch,hyperv,sriovnicswitch')

    def test_is_nfg_logging_enabled(self):
        self.os_release.return_value = 'stein'
        self.test_config.set('enable-firewall-group-logging', True)
        self.assertTrue(context.is_nfg_logging_enabled())
        self.os_release.return_value = 'stein'
        self.test_config.set('enable-firewall-group-logging', False)
        self.assertFalse(context.is_nfg_logging_enabled())
        self.os_release.return_value = 'queens'
        self.test_config.set('enable-firewall-group-logging', True)
        self.assertFalse(context.is_nfg_logging_enabled())

    def test_is_port_forwarding_enabled(self):
        self.os_release.return_value = 'rocky'
        self.test_config.set('enable-port-forwarding', True)
        self.assertTrue(context.is_port_forwarding_enabled())
        self.os_release.return_value = 'rocky'
        self.test_config.set('enable-port-forwarding', False)
        self.assertFalse(context.is_port_forwarding_enabled())
        self.os_release.return_value = 'queens'
        self.test_config.set('enable-port-forwarding', True)
        self.assertFalse(context.is_port_forwarding_enabled())


class IdentityServiceContext(CharmTestCase):

    def setUp(self):
        super(IdentityServiceContext, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.test_config.set('region', 'region457')
        self.test_config.set('prefer-ipv6', False)

    @patch.object(charmhelpers.contrib.openstack.context, 'os_release')
    @patch.object(charmhelpers.contrib.openstack.context, 'format_ipv6_addr')
    @patch.object(charmhelpers.contrib.openstack.context, 'context_complete')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt(self, _log, _rids, _runits, _rget, _ctxt_comp,
                      format_ipv6_addr, _os_release):
        _os_release.return_value = 'rocky'
        _rids.return_value = 'rid1'
        _runits.return_value = 'runit'
        _ctxt_comp.return_value = True
        id_data = {
            'service_port': 9876,
            'service_host': '127.0.0.4',
            'auth_host': '127.0.0.5',
            'auth_port': 5432,
            'service_tenant': 'ten',
            'service_username': 'admin',
            'service_password': 'adminpass',
        }
        _rget.return_value = id_data
        ids_ctxt = context.IdentityServiceContext()
        self.assertEqual(ids_ctxt()['region'], 'region457')

    @patch.object(charmhelpers.contrib.openstack.context, 'os_release')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_ids_ctxt_no_rels(self, _log, _rids, _os_release):
        _os_release.return_value = 'rocky'
        _rids.return_value = []
        ids_ctxt = context.IdentityServiceContext()
        self.assertEqual(ids_ctxt(), None)


class HAProxyContextTest(CharmTestCase):

    def setUp(self):
        super(HAProxyContextTest, self).setUp(context, TO_PATCH)
        self.determine_api_port.return_value = 9686
        self.determine_apache_port.return_value = 9686
        self.api_port = 9696

    def tearDown(self):
        super(HAProxyContextTest, self).tearDown()

    @patch.object(charmhelpers.contrib.openstack.context, 'mkdir')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    def test_context_No_peers(self, _log, _rids, _mkdir):
        _rids.return_value = []
        hap_ctxt = context.HAProxyContext()
        with patch('builtins.__import__'):
            self.assertTrue('units' not in hap_ctxt())

    @patch.object(charmhelpers.contrib.openstack.context, 'get_relation_ip')
    @patch.object(charmhelpers.contrib.openstack.context, 'mkdir')
    @patch.object(
        charmhelpers.contrib.openstack.context, 'get_netmask_for_address')
    @patch.object(
        charmhelpers.contrib.openstack.context, 'get_address_in_network')
    @patch.object(charmhelpers.contrib.openstack.context, 'config')
    @patch.object(charmhelpers.contrib.openstack.context, 'local_unit')
    @patch.object(charmhelpers.contrib.openstack.context, 'unit_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    @patch.object(charmhelpers.contrib.openstack.context, 'kv')
    @patch('builtins.__import__')
    @patch('builtins.open')
    def test_context_peers(self, _open, _import, _kv, _log, _rids, _runits,
                           _rget, _uget, _lunit, _config,
                           _get_address_in_network, _get_netmask_for_address,
                           _mkdir, _get_relation_ip):
        unit_addresses = {
            'neutron-api-0': '10.10.10.10',
            'neutron-api-1': '10.10.10.11',
        }
        _rids.return_value = ['rid1']
        _runits.return_value = ['neutron-api/0']
        _rget.return_value = unit_addresses['neutron-api-0']
        _lunit.return_value = "neutron-api/1"
        _uget.return_value = unit_addresses['neutron-api-1']
        _get_relation_ip.return_value = unit_addresses['neutron-api-1']
        _config.return_value = None
        _get_address_in_network.return_value = None
        _get_netmask_for_address.return_value = '255.255.255.0'
        _kv().get.return_value = 'abcdefghijklmnopqrstuvwxyz123456'
        service_ports = {'neutron-server': [9696, 9686]}
        ctxt_data = {
            'local_host': '127.0.0.1',
            'haproxy_host': '0.0.0.0',
            'local_host': '127.0.0.1',
            'stat_port': '8888',
            'stat_password': 'abcdefghijklmnopqrstuvwxyz123456',
            'frontends': {
                '10.10.10.11': {
                    'network': '10.10.10.11/255.255.255.0',
                    'backends': unit_addresses,
                }
            },
            'default_backend': '10.10.10.11',
            'service_ports': service_ports,
            'neutron_bind_port': 9686,
            'ipv6_enabled': True,
        }
        _import().api_port.return_value = 9696
        hap_ctxt = context.HAProxyContext()
        self.maxDiff = None
        self.assertEqual(hap_ctxt(), ctxt_data)
        _open.assert_called_with('/etc/default/haproxy', 'w')


class NeutronCCContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronCCContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.api_port = 9696
        self.determine_api_port.return_value = self.api_port
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('neutron-security-groups', True)
        self.test_config.set('debug', True)
        self.test_config.set('verbose', True)
        self.test_config.set('neutron-external-network', 'bob')
        self.test_config.set('nsx-username', 'bob')
        self.test_config.set('nsx-password', 'hardpass')
        self.test_config.set('nsx-tz-uuid', 'tzuuid')
        self.test_config.set('nsx-l3-uuid', 'l3uuid')
        self.test_config.set('nsx-controllers', 'ctrl1 ctrl2')
        self.test_config.set('vsd-server', '192.168.2.202')
        self.test_config.set('vsd-auth', 'fooadmin:password')
        self.test_config.set('vsd-organization', 'foo')
        self.test_config.set('vsd-base-uri', '/nuage/api/v1_0')
        self.test_config.set('vsd-netpart-name', 'foo-enterprise')
        self.test_config.set('plumgrid-username', 'plumgrid')
        self.test_config.set('plumgrid-password', 'plumgrid')
        self.test_config.set('plumgrid-virtual-ip', '192.168.100.250')
        self.test_config.set('midonet-origin', 'mem-1.9')
        self.test_config.set('mem-username', 'yousir')
        self.test_config.set('mem-password', 'heslo')
        self.test_config.set('enable-ml2-port-security', True)
        self.test_config.set('dhcp-agents-per-network', 3)
        # Although set as True for all tests, only Ussuri templates
        # can apply this option.
        self.test_config.set('enable-igmp-snooping', True)

    def tearDown(self):
        super(NeutronCCContextTest, self).tearDown()

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_no_setting(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        ctxt_data = {
            'debug': True,
            'enable_dvr': False,
            'l3_ha': False,
            'allow_automatic_dhcp_failover': True,
            'allow_automatic_l3agent_failover': False,
            'mechanism_drivers': 'openvswitch,l2population',
            'dhcp_agents_per_network': 3,
            'enable_sriov': False,
            'external_network': 'bob',
            'enable_igmp_snooping': True,
            'neutron_bind_port': self.api_port,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'gre',
            'tenant_network_types': 'gre,vlan,flat,local',
            'quota_floatingip': 50,
            'quota_health_monitors': -1,
            'quota_member': -1,
            'quota_network': 10,
            'quota_pool': 10,
            'quota_port': 50,
            'quota_router': 10,
            'quota_security_group': 10,
            'quota_security_group_rule': 100,
            'quota_subnet': 10,
            'quota_vip': 10,
            'vlan_ranges': 'physnet1:1000:2000',
            'vni_ranges': '1001:2000',
            'extension_drivers': 'port_security',
            'service_plugins': (
                'neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,'
                'neutron.services.firewall.fwaas_plugin.FirewallPlugin,'
                'neutron.services.loadbalancer.plugin.LoadBalancerPlugin,'
                'neutron.services.vpn.plugin.VPNDriverPlugin,'
                'neutron.services.metering.metering_plugin.MeteringPlugin'),
        }
        napi_ctxt = context.NeutronCCContext()
        self.os_release.return_value = 'icehouse'
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertEqual(ctxt_data, napi_ctxt())

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_no_setting_mitaka(self, _import, plugin, nm,
                                                 nlb):
        plugin.return_value = None
        ctxt_data = {
            'debug': True,
            'enable_dvr': False,
            'l3_ha': False,
            'allow_automatic_dhcp_failover': True,
            'allow_automatic_l3agent_failover': False,
            'mechanism_drivers': 'openvswitch,hyperv,l2population',
            'dhcp_agents_per_network': 3,
            'enable_sriov': False,
            'external_network': 'bob',
            'global_physnet_mtu': 1500,
            'enable_igmp_snooping': True,
            'neutron_bind_port': self.api_port,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'gre',
            'path_mtu': 1500,
            'tenant_network_types': 'gre,vlan,flat,local',
            'quota_floatingip': 50,
            'quota_health_monitors': -1,
            'quota_member': -1,
            'quota_network': 10,
            'quota_pool': 10,
            'quota_port': 50,
            'quota_router': 10,
            'quota_security_group': 10,
            'quota_security_group_rule': 100,
            'quota_subnet': 10,
            'quota_vip': 10,
            'vlan_ranges': 'physnet1:1000:2000',
            'vni_ranges': '1001:2000',
            'extension_drivers': 'port_security',
            'service_plugins': 'router,firewall,lbaas,vpnaas,metering',
            'network_scheduler_driver': (
                'neutron.scheduler.dhcp_agent_scheduler'
                '.AZAwareWeightScheduler'),
            'dhcp_load_type': 'networks',
        }
        napi_ctxt = context.NeutronCCContext()
        self.maxDiff = None
        self.os_release.return_value = 'mitaka'
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertEqual(ctxt_data, napi_ctxt())

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    def test_neutroncc_context_dns_setting(self, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('enable-ml2-dns', True)
        self.test_config.set('dns-domain', 'example.org.')
        self.os_release.return_value = 'mitaka'
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertEqual('example.org.', ctxt['dns_domain'])
            self.assertEqual('port_security,dns', ctxt['extension_drivers'])

        self.os_release.return_value = 'queens'
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertEqual('example.org.', ctxt['dns_domain'])
            self.assertEqual('port_security,dns_domain_ports',
                             ctxt['extension_drivers'])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    def test_neutroncc_context_dns_no_port_security_setting(self,
                                                            plugin, nm, nlb):
        """Verify extension drivers without port security."""
        plugin.return_value = None
        self.test_config.set('enable-ml2-port-security', False)
        self.test_config.set('enable-ml2-dns', True)
        self.test_config.set('dns-domain', 'example.org.')
        self.os_release.return_value = 'mitaka'
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertEqual('example.org.', ctxt['dns_domain'])
            self.assertEqual('dns', ctxt['extension_drivers'])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    def test_neutroncc_context_dns_kilo(self, plugin, nm, nlb):
        """Verify dns extension and domain are not specified in kilo."""
        plugin.return_value = None
        self.test_config.set('enable-ml2-port-security', False)
        self.test_config.set('enable-ml2-dns', True)
        self.test_config.set('dns-domain', 'example.org.')
        self.os_release.return_value = 'kilo'
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertFalse('dns_domain' in ctxt)
            self.assertFalse('extension_drivers' in ctxt)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_vxlan(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('flat-network-providers', 'physnet2 physnet3')
        self.test_config.set('overlay-network-type', 'vxlan')
        self.test_config.set('vni-ranges', '1001:2000 3001:4000')
        ctxt_data = {
            'debug': True,
            'enable_dvr': False,
            'l3_ha': False,
            'allow_automatic_dhcp_failover': True,
            'allow_automatic_l3agent_failover': False,
            'mechanism_drivers': 'openvswitch,l2population',
            'dhcp_agents_per_network': 3,
            'enable_sriov': False,
            'external_network': 'bob',
            'enable_igmp_snooping': True,
            'neutron_bind_port': self.api_port,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'vxlan',
            'tenant_network_types': 'vxlan,vlan,flat,local',
            'quota_floatingip': 50,
            'quota_health_monitors': -1,
            'quota_member': -1,
            'quota_network': 10,
            'quota_pool': 10,
            'quota_port': 50,
            'quota_router': 10,
            'quota_security_group': 10,
            'quota_security_group_rule': 100,
            'quota_subnet': 10,
            'quota_vip': 10,
            'vlan_ranges': 'physnet1:1000:2000',
            'vni_ranges': '1001:2000,3001:4000',
            'network_providers': 'physnet2,physnet3',
            'extension_drivers': 'port_security',
            'service_plugins': (
                'neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,'
                'neutron.services.firewall.fwaas_plugin.FirewallPlugin,'
                'neutron.services.loadbalancer.plugin.LoadBalancerPlugin,'
                'neutron.services.vpn.plugin.VPNDriverPlugin,'
                'neutron.services.metering.metering_plugin.MeteringPlugin'),
        }
        napi_ctxt = context.NeutronCCContext()
        self.os_release.return_value = 'icehouse'
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertEqual(ctxt_data, napi_ctxt())

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_l3ha(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('enable-qos', False)
        self.test_config.set('enable-vlan-trunking', False)
        self.test_config.set('overlay-network-type', 'gre')
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('l2-population', False)
        self.os_release.return_value = 'juno'
        self.maxDiff = None
        ctxt_data = {
            'debug': True,
            'enable_dvr': False,
            'l3_ha': True,
            'mechanism_drivers': 'openvswitch',
            'external_network': 'bob',
            'enable_igmp_snooping': True,
            'neutron_bind_port': self.api_port,
            'verbose': True,
            'l2_population': False,
            'overlay_network_type': 'gre',
            'tenant_network_types': 'gre,vlan,flat,local',
            'max_l3_agents_per_router': 2,
            'min_l3_agents_per_router': 2,
            'allow_automatic_dhcp_failover': True,
            'allow_automatic_l3agent_failover': False,
            'dhcp_agents_per_network': 3,
            'enable_sriov': False,
            'quota_floatingip': 50,
            'quota_health_monitors': -1,
            'quota_member': -1,
            'quota_network': 10,
            'quota_pool': 10,
            'quota_port': 50,
            'quota_router': 10,
            'quota_security_group': 10,
            'quota_security_group_rule': 100,
            'quota_subnet': 10,
            'quota_vip': 10,
            'vlan_ranges': 'physnet1:1000:2000',
            'vni_ranges': '1001:2000',
            'extension_drivers': 'port_security',
            'service_plugins': (
                'neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,'
                'neutron.services.firewall.fwaas_plugin.FirewallPlugin,'
                'neutron.services.loadbalancer.plugin.LoadBalancerPlugin,'
                'neutron.services.vpn.plugin.VPNDriverPlugin,'
                'neutron.services.metering.metering_plugin.MeteringPlugin'),
        }
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertEqual(ctxt_data, napi_ctxt())

    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_l3ha_l3_agents(self, _import, plugin, nm):
        plugin.return_value = None
        self.os_release.return_value = 'juno'
        self.test_config.set('enable-l3ha', True)
        self.test_config.set('l2-population', False)
        self.test_config.set('max-l3-agents-per-router', 2)
        self.test_config.set('min-l3-agents-per-router', 3)
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertRaises(ValueError, napi_ctxt)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_sriov(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('enable-sriov', True)
        self.test_config.set('supported-pci-vendor-devs',
                             '1111:3333  2222:4444')
        ctxt_data = {
            'debug': True,
            'enable_dvr': False,
            'l3_ha': False,
            'allow_automatic_dhcp_failover': True,
            'allow_automatic_l3agent_failover': False,
            'mechanism_drivers': 'openvswitch,hyperv,l2population'
                                 ',sriovnicswitch',
            'dhcp_agents_per_network': 3,
            'enable_sriov': True,
            'supported_pci_vendor_devs': '1111:3333,2222:4444',
            'external_network': 'bob',
            'enable_igmp_snooping': True,
            'neutron_bind_port': self.api_port,
            'verbose': True,
            'l2_population': True,
            'overlay_network_type': 'gre',
            'tenant_network_types': 'gre,vlan,flat,local',
            'quota_floatingip': 50,
            'quota_health_monitors': -1,
            'quota_member': -1,
            'quota_network': 10,
            'quota_pool': 10,
            'quota_port': 50,
            'quota_router': 10,
            'quota_security_group': 10,
            'quota_security_group_rule': 100,
            'quota_subnet': 10,
            'quota_vip': 10,
            'vlan_ranges': 'physnet1:1000:2000',
            'vni_ranges': '1001:2000',
            'extension_drivers': 'port_security',
            'service_plugins': 'router,firewall,lbaas,vpnaas,metering',
        }
        napi_ctxt = context.NeutronCCContext()
        self.os_release.return_value = 'kilo'
        with patch.object(napi_ctxt, '_ensure_packages'):
            self.assertEqual(ctxt_data, napi_ctxt())

    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_unsupported_overlay(self, _import, plugin, nm):
        plugin.return_value = None
        self.test_config.set('overlay-network-type', 'bobswitch')
        with self.assertRaises(Exception) as context:
            context.NeutronCCContext()

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_api_rel(self, _import, plugin, nm, nlb):
        nova_url = 'http://127.0.0.10'
        plugin.return_value = None
        self.os_release.return_value = 'havana'
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid2']
        self.test_relation.set({'nova_url': nova_url,
                                'restart_trigger': 'bob'})
        napi_ctxt = context.NeutronCCContext()
        self.assertEqual(nova_url, napi_ctxt()['nova_url'])
        self.assertEqual('bob', napi_ctxt()['restart_trigger'])
        self.assertEqual(self.api_port, napi_ctxt()['neutron_bind_port'])

    def test_neutroncc_context_manager(self):
        napi_ctxt = context.NeutronCCContext()
        self.assertEqual(napi_ctxt.network_manager, 'neutron')
        self.assertEqual(napi_ctxt.plugin, 'ovs')
        self.assertEqual(napi_ctxt.neutron_security_groups, True)

    def test_neutroncc_context_manager_pkgs(self):
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages') as ep:
            napi_ctxt._ensure_packages()
            ep.assert_has_calls([])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_nsx(self, _import, plugin, nm, nlb):
        plugin.return_value = 'nsx'
        self.os_release.return_value = 'havana'
        self.related_units.return_value = []
        self.test_config.set('neutron-plugin', 'nsx')
        napi_ctxt = context.NeutronCCContext()()
        expect = {
            'nsx_controllers': 'ctrl1,ctrl2',
            'nsx_controllers_list': ['ctrl1', 'ctrl2'],
            'nsx_l3_uuid': 'l3uuid',
            'nsx_password': 'hardpass',
            'nsx_tz_uuid': 'tzuuid',
            'nsx_username': 'bob',
        }
        for key in expect.keys():
            self.assertEqual(napi_ctxt[key], expect[key])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_nuage(self, _import, plugin, nm, nlb):
        plugin.return_value = 'vsp'
        self.os_release.return_value = 'havana'
        self.related_units.return_value = ['vsdunit1']
        self.relation_ids.return_value = ['vsdrid2']
        self.test_config.set('neutron-plugin', 'vsp')
        napi_ctxt = context.NeutronCCContext()()
        expect = {
            'vsd_server': '192.168.2.202',
            'vsd_auth': 'fooadmin:password',
            'vsd_organization': 'foo',
            'vsd_base_uri': '/nuage/api/v1_0',
            'vsd_netpart_name': 'foo-enterprise',
        }
        for key in expect.keys():
            self.assertEqual(napi_ctxt[key], expect[key])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_qos(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.os_release.return_value = 'mitaka'
        self.test_config.set('enable-qos', True)
        self.test_config.set('enable-ml2-port-security', False)
        napi_ctxt = context.NeutronCCContext()()
        service_plugins = ('router,firewall,lbaas,vpnaas,metering,qos')
        expect = {
            'extension_drivers': 'qos',
            'service_plugins': service_plugins,
        }
        for key in expect.keys():
            self.assertEqual(napi_ctxt[key], expect[key])

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_vlan_trunking(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.os_release.return_value = 'newton'
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('enable-vlan-trunking', True)
        napi_ctxt = context.NeutronCCContext()()
        expected_service_plugins = ('router,firewall,vpnaas,metering,'
                                    'neutron_lbaas.services.loadbalancer.'
                                    'plugin.LoadBalancerPluginv2,trunk')
        self.assertEqual(napi_ctxt['service_plugins'],
                         expected_service_plugins)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_vlan_trunking_invalid_plugin(self, _import,
                                                            plugin, nm, nlb):
        plugin.return_value = None
        self.os_release.return_value = 'newton'
        self.test_config.set('neutron-plugin', 'Calico')
        self.test_config.set('enable-vlan-trunking', True)
        napi_ctxt = context.NeutronCCContext()()
        expected_service_plugins = ('router,firewall,vpnaas,metering,'
                                    'neutron_lbaas.services.loadbalancer.'
                                    'plugin.LoadBalancerPluginv2')
        self.assertEqual(napi_ctxt['service_plugins'],
                         expected_service_plugins)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_vlan_trunking_invalid_release(self, _import,
                                                             plugin, nm, nlb):
        plugin.return_value = None
        self.os_release.return_value = 'mitaka'
        self.test_config.set('neutron-plugin', 'ovs')
        self.test_config.set('enable-vlan-trunking', True)
        napi_ctxt = context.NeutronCCContext()()
        expected_service_plugins = ('router,firewall,lbaas,vpnaas,metering')
        self.assertEqual(napi_ctxt['service_plugins'],
                         expected_service_plugins)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    @patch('builtins.__import__')
    def test_neutroncc_context_service_plugins(self, _import, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('enable-qos', False)
        self.test_config.set('enable-ml2-port-security', False)
        self.test_config.set('enable-vlan-trunking', False)
        # icehouse
        self.os_release.return_value = 'icehouse'
        service_plugins = (
            'neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,'
            'neutron.services.firewall.fwaas_plugin.FirewallPlugin,'
            'neutron.services.loadbalancer.plugin.LoadBalancerPlugin,'
            'neutron.services.vpn.plugin.VPNDriverPlugin,'
            'neutron.services.metering.metering_plugin.MeteringPlugin')
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # juno
        self.os_release.return_value = 'juno'
        service_plugins = (
            'neutron.services.l3_router.l3_router_plugin.L3RouterPlugin,'
            'neutron.services.firewall.fwaas_plugin.FirewallPlugin,'
            'neutron.services.loadbalancer.plugin.LoadBalancerPlugin,'
            'neutron.services.vpn.plugin.VPNDriverPlugin,'
            'neutron.services.metering.metering_plugin.MeteringPlugin')
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # kilo
        self.os_release.return_value = 'kilo'
        service_plugins = 'router,firewall,lbaas,vpnaas,metering'
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # liberty
        self.os_release.return_value = 'liberty'
        service_plugins = 'router,firewall,lbaas,vpnaas,metering'
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # mitaka
        self.os_release.return_value = 'mitaka'
        service_plugins = 'router,firewall,lbaas,vpnaas,metering'
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # newton
        self.os_release.return_value = 'newton'
        service_plugins = (
            'router,firewall,vpnaas,metering,'
            'neutron_lbaas.services.loadbalancer.plugin.LoadBalancerPluginv2')
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # ocata
        self.os_release.return_value = 'ocata'
        service_plugins = (
            'router,firewall,vpnaas,metering,'
            'neutron_lbaas.services.loadbalancer.plugin.LoadBalancerPluginv2,'
            'segments,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin'
        )
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # pike
        self.os_release.return_value = 'pike'
        service_plugins = (
            'router,firewall,metering,segments,'
            'neutron_lbaas.services.loadbalancer.plugin.LoadBalancerPluginv2,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin')
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # queens
        self.os_release.return_value = 'pike'
        service_plugins = (
            'router,firewall,metering,segments,'
            'neutron_lbaas.services.loadbalancer.plugin.LoadBalancerPluginv2,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin')
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)
        # rocky
        self.os_release.return_value = 'rocky'
        service_plugins = (
            'router,firewall,metering,segments,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin,'
            'lbaasv2')
        ncc_context = context.NeutronCCContext()()
        self.assertEqual(ncc_context['service_plugins'],
                         service_plugins)

        # stein
        self.os_release.return_value = 'stein'
        service_plugins = (
            'router,firewall_v2,metering,segments,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin,'
            'lbaasv2')
        ncc_context = context.NeutronCCContext()()
        self.assertEqual(ncc_context['service_plugins'],
                         service_plugins)
        self.assertTrue(ncc_context['firewall_v2'])

        # rocky and related to charm through neutron-load-balancer interface
        self.os_release.return_value = 'rocky'
        service_plugins = (
            'router,firewall,metering,segments,'
            'neutron_dynamic_routing.services.bgp.bgp_plugin.BgpPlugin,'
            'lbaasv2-proxy')
        lb_context = MagicMock()
        lb_context.return_value = {'load_balancer_name': 'octavia'}
        nlb.return_value = lb_context
        self.assertEqual(context.NeutronCCContext()()['service_plugins'],
                         service_plugins)

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    def test_neutroncc_context_physical_network_mtus(self, plugin, nm, nlb):
        plugin.return_value = None
        self.test_config.set('physical-network-mtus', 'provider1:4000')
        self.os_release.return_value = 'mitaka'
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertEqual(ctxt['physical_network_mtus'], 'provider1:4000')

    @patch.object(context, 'NeutronLoadBalancerContext')
    @patch.object(context.NeutronCCContext, 'network_manager')
    @patch.object(context.NeutronCCContext, 'plugin')
    def test_neutroncc_context_physical_network_mtus_multi(self, plugin, nm,
                                                           nlb):
        plugin.return_value = None
        self.test_config.set('physical-network-mtus',
                             'provider1:4000 provider2:5000')
        self.os_release.return_value = 'mitaka'
        napi_ctxt = context.NeutronCCContext()
        with patch.object(napi_ctxt, '_ensure_packages'):
            ctxt = napi_ctxt()
            self.assertEqual(ctxt['physical_network_mtus'],
                             'provider1:4000,provider2:5000')


class EtcdContextTest(CharmTestCase):

    def setUp(self):
        super(EtcdContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.test_config.set('neutron-plugin', 'Calico')

    def tearDown(self):
        super(EtcdContextTest, self).tearDown()

    def test_etcd_no_related_units(self):
        self.related_units.return_value = []
        ctxt = context.EtcdContext()()
        expect = {'cluster': ''}

        self.assertEqual(expect, ctxt)

    def test_some_related_units(self):
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid2', 'rid3']
        result = (
            'testname=http://172.18.18.18:8888,'
            'testname=http://172.18.18.18:8888'
        )
        self.test_relation.set({'cluster': result})

        ctxt = context.EtcdContext()()
        expect = {'cluster': result}

        self.assertEqual(expect, ctxt)

    def test_early_exit(self):
        self.test_config.set('neutron-plugin', 'notCalico')

        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid2', 'rid3']
        self.test_relation.set({'ip': '172.18.18.18',
                                'port': 8888,
                                'name': 'testname'})

        ctxt = context.EtcdContext()()
        expect = {'cluster': ''}

        self.assertEqual(expect, ctxt)


class NeutronApiSDNContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronApiSDNContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get

    def tearDown(self):
        super(NeutronApiSDNContextTest, self).tearDown()

    def test_init(self):
        napisdn_ctxt = context.NeutronApiSDNContext()
        self.assertEqual(
            napisdn_ctxt.interfaces,
            ['neutron-plugin-api-subordinate']
        )
        self.assertEqual(napisdn_ctxt.services, ['neutron-api'])
        self.assertEqual(
            napisdn_ctxt.config_file,
            '/etc/neutron/neutron.conf'
        )

    @patch.object(charmhelpers.contrib.openstack.context, 'log')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_get')
    @patch.object(charmhelpers.contrib.openstack.context, 'related_units')
    @patch.object(charmhelpers.contrib.openstack.context, 'relation_ids')
    def ctxt_check(self, rel_settings, expect, _rids, _runits, _rget, _log,
                   defaults=None, not_defaults=None):
        self.test_relation.set(rel_settings)
        _runits.return_value = ['unit1']
        _rids.return_value = ['rid2']
        _rget.side_effect = self.test_relation.get
        self.relation_ids.return_value = ['rid2']
        self.related_units.return_value = ['unit1']
        napisdn_instance = context.NeutronApiSDNContext()
        napisdn_ctxt = napisdn_instance()
        self.assertEqual(napisdn_ctxt, expect)
        defaults = defaults or []
        for templ_key in defaults:
            self.assertTrue(napisdn_instance.is_default(templ_key))
        not_defaults = not_defaults or []
        for templ_key in not_defaults:
            self.assertFalse(napisdn_instance.is_default(templ_key))

    def test_defaults(self):
        self.ctxt_check(
            {'neutron-plugin': 'ovs'},
            {
                'core_plugin': 'neutron.plugins.ml2.plugin.Ml2Plugin',
                'neutron_plugin_config': ('/etc/neutron/plugins/ml2/'
                                          'ml2_conf.ini'),
                'neutron_plugin': 'ovs',
                'sections': {},
            },
            defaults=['core_plugin', 'neutron_plugin_config'],
        )

    def test_overrides(self):
        self.ctxt_check(
            {
                'neutron-plugin': 'ovs',
                'api-extensions-path': '/usr/local/share/neutron/extensions',
                'core-plugin': 'neutron.plugins.ml2.plugin.MidoPlumODL',
                'neutron-plugin-config': '/etc/neutron/plugins/fl/flump.ini',
                'service-plugins': 'router,unicorn,rainbows',
                'restart-trigger': 'restartnow',
                'quota-driver': 'quotadriver',
                'extension-drivers': 'dns,port_security',
                'mechanism-drivers': 'ovn',
                'tenant-network-types': 'geneve,gre,vlan,flat,local',
                'neutron-security-groups': 'true',
            },
            {
                'api_extensions_path': '/usr/local/share/neutron/extensions',
                'core_plugin': 'neutron.plugins.ml2.plugin.MidoPlumODL',
                'neutron_plugin_config': '/etc/neutron/plugins/fl/flump.ini',
                'service_plugins': 'router,unicorn,rainbows',
                'restart_trigger': 'restartnow',
                'quota_driver': 'quotadriver',
                'neutron_plugin': 'ovs',
                'extension_drivers': 'dns,port_security',
                'mechanism_drivers': 'ovn',
                'tenant_network_types': 'geneve,gre,vlan,flat,local',
                'neutron_security_groups': 'true',
                'sections': {},
            },
            not_defaults=[
                'api_extensions_path', 'core_plugin', 'neutron_plugin_config',
                'service_plugins', 'restart_trigger', 'quota_driver',
                'extension_drivers', 'mechanism_drivers',
                'tenant_network_types', 'neutron_security_groups',
            ],
        )

    def test_subordinateconfig(self):
        principle_config = {
            "neutron-api": {
                "/etc/neutron/neutron.conf": {
                    "sections": {
                        'DEFAULT': [
                            ('neutronboost', True)
                        ],
                    }
                }
            }
        }
        self.ctxt_check(
            {
                'neutron-plugin': 'ovs',
                'subordinate_configuration': json.dumps(principle_config),
            },
            {
                'core_plugin': 'neutron.plugins.ml2.plugin.Ml2Plugin',
                'neutron_plugin_config': ('/etc/neutron/plugins/ml2/'
                                          'ml2_conf.ini'),
                'neutron_plugin': 'ovs',
                'sections': {u'DEFAULT': [[u'neutronboost', True]]},
            }
        )

    def test_empty(self):
        self.ctxt_check(
            {},
            {},
        )

    def test_is_allowed(self):
        napisdn_instance = context.NeutronApiSDNContext()
        self.assertTrue(napisdn_instance.is_allowed('core_plugin'))
        self.assertFalse(napisdn_instance.is_allowed('non_existent_key'))


class NeutronApiSDNConfigFileContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronApiSDNConfigFileContextTest, self).setUp(
            context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get

    def tearDown(self):
        super(NeutronApiSDNConfigFileContextTest, self).tearDown()

    def test_configset(self):
        self.test_relation.set({
            'neutron-plugin-config': '/etc/neutron/superplugin.ini'
        })
        self.relation_ids.return_value = ['rid2']
        self.related_units.return_value = ['unit1']
        napisdn_ctxt = context.NeutronApiSDNConfigFileContext()()
        self.assertEqual(napisdn_ctxt, {
            'config': '/etc/neutron/superplugin.ini'
        })

    def test_default(self):
        self.relation_ids.return_value = ['rid3']
        self.related_units.return_value = ['unit2']
        napisdn_ctxt = context.NeutronApiSDNConfigFileContext()()
        self.assertEqual(napisdn_ctxt, {
            'config': '/etc/neutron/plugins/ml2/ml2_conf.ini'
        })

    def test_no_related_unites(self):
        self.relation_ids.return_value = ['rid4']
        napisdn_ctxt = context.NeutronApiSDNConfigFileContext()()
        self.assertEqual(napisdn_ctxt, {})


class NeutronApiApiPasteContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronApiApiPasteContextTest, self).setUp(
            context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get

    def tearDown(self):
        super(NeutronApiApiPasteContextTest, self).tearDown()

    def test_default(self):
        middleware = []

        self.test_relation.set({
            'extra_middleware': repr(middleware)
        })

        self.relation_ids.return_value = ['rid']
        self.related_units.return_value = ['testunit']

        self.assertRaises(ValueError, context.NeutronApiApiPasteContext())

    def test_string(self):
        self.test_relation.set({'extra_middleware': 'n42'})

        self.relation_ids.return_value = ['rid']
        self.related_units.return_value = ['testunit']

        self.assertRaises(ValueError, context.NeutronApiApiPasteContext())

    def test_dict(self):
        self.test_relation.set({'extra_middleware':
                                {'dict_with': 'something'}})

        self.relation_ids.return_value = ['rid']
        self.related_units.return_value = ['testunit']

        self.assertRaises(ValueError, context.NeutronApiApiPasteContext())

    def test_configset(self):
        middleware = [{'name': 'middleware_1',
                       'type': 'filter',
                       'config': {'setting_1': 'value_1'}},
                      {'name': 'middleware_2',
                       'type': 'app',
                       'config': {'setting_2': 'value_2'}}
                      ]

        # note repr is needed to simulate charm-helpers behavior
        # with regards to object serialization - the context
        # implementation should safely eval the string instead
        # of just using it
        self.test_relation.set({
            'extra_middleware': repr(middleware)
        })
        self.relation_ids.return_value = ['rid2']
        self.related_units.return_value = ['unit1']
        napiapipaste_ctxt = context.NeutronApiApiPasteContext()()
        self.assertEqual(napiapipaste_ctxt, {'extra_middleware': middleware})

    def __test_arg(self, key):
        middleware = [{'name': 'middleware_1',
                       'type': 'filter',
                       'config': {'setting_1': 'value_1'}},
                      {'name': 'middleware_2',
                       'type': 'composite',
                       'config': {'setting_2': 'value_2'}}]
        # invalidate a key
        middleware[0][key] = None

        self.test_relation.set({
            'extra_middleware': repr(middleware)
        })

        self.relation_ids.return_value = ['rid']
        self.related_units.return_value = ['testunit']

        self.assertRaises(ValueError, context.NeutronApiApiPasteContext())

    def test_no_type(self):
        self.__test_arg('type')

    def test_no_name(self):
        self.__test_arg('name')

    def test_no_config(self):
        self.__test_arg('config')


class MidonetContextTest(CharmTestCase):

    def setUp(self):
        super(MidonetContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.test_config.set('neutron-plugin', 'midonet')
        self.test_config.set('midonet-origin', 'midonet-2015.06')

    def tearDown(self):
        super(MidonetContextTest, self).tearDown()

    def test_midonet_no_related_units(self):
        self.related_units.return_value = []
        ctxt = context.MidonetContext()()
        expect = {}

        self.assertEqual(expect, ctxt)

    def test_some_related_units(self):
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        self.test_relation.set({'host': '11.11.11.11',
                                'port': '8080'})
        ctxt = context.MidonetContext()()
        expect = {'midonet_api_ip': '11.11.11.11',
                  'midonet_api_port': '8080'}

        self.assertEqual(expect, ctxt)


class CiscoAciContextTest(CharmTestCase):

    def setUp(self):
        super(CiscoAciContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get
        self.test_config.set('neutron-plugin', 'aci')

    def tearDown(self):
        super(CiscoAciContextTest, self).tearDown()

    def test_ciscoaci_no_related_units(self):
        self.related_units.return_value = []
        ctxt = context.CiscoAciContext()()
        expect = {}

        self.assertEqual(expect, ctxt)

    def test_ciscoaci_some_related_units(self):
        self.related_units.return_value = ['aciunit1']
        self.relation_ids.return_value = ['aciid1']
        self.test_relation.set({'neutron_plugin': 'aci', 'aci_apic_system_id': 'openstack', 'aci_encap':'vxlan'})
        ctxt = context.CiscoAciContext()()
        expect = {'neutron_plugin': 'aci',
                  'aci_apic_system_id': 'openstack',
                  'aci_encap': 'vxlan'}

        self.assertEqual(expect, ctxt)

    def test_ciscoaci_wrong_plugin_name(self):
        self.related_units.return_value = ['aciunit1']
        self.relation_ids.return_value = ['aciid1']
        self.test_relation.set({'neutron_plugin': 'aci1', 'aci_apic_system_id': 'openstack', 'aci_encap':'vxlan'})
        ctxt = context.CiscoAciContext()()
        expect = {}

        self.assertEqual(expect, ctxt)


class DesignateContextTest(CharmTestCase):

    def setUp(self):
        super(DesignateContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get

    def tearDown(self):
        super(DesignateContextTest, self).tearDown()

    def test_designate_no_related_units(self):
        self.related_units.return_value = []
        ctxt = context.DesignateContext()()
        expect = {}

        self.assertEqual(expect, ctxt)

    def test_designate_related_units_no_reverse_dns_lookup(self):
        self.config.side_effect = self.test_config.get
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        self.test_relation.set({'endpoint': 'http://1.1.1.1:9001'})
        self.test_config.set('reverse-dns-lookup', False)
        ctxt = context.DesignateContext()()
        expect = {'enable_designate': True,
                  'designate_endpoint': 'http://1.1.1.1:9001',
                  'allow_reverse_dns_lookup': False}

        self.assertEqual(expect, ctxt)

    def test_designate_related_units_and_reverse_dns_lookup(self):
        self.config.side_effect = self.test_config.get
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        self.test_relation.set({'endpoint': 'http://1.1.1.1:9001'})
        self.test_config.set('reverse-dns-lookup', True)
        self.test_config.set('ipv4-ptr-zone-prefix-size', 24)
        self.test_config.set('ipv6-ptr-zone-prefix-size', 64)
        ctxt = context.DesignateContext()()
        expect = {'enable_designate': True,
                  'designate_endpoint': 'http://1.1.1.1:9001',
                  'allow_reverse_dns_lookup': True,
                  'ipv4_ptr_zone_prefix_size': 24,
                  'ipv6_ptr_zone_prefix_size': 64}

        self.assertEqual(expect, ctxt)


class NeutronLoadBalancerContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronLoadBalancerContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get

    def tearDown(self):
        super(NeutronLoadBalancerContextTest, self).tearDown()

    def test_neutron_load_balancer_context(self):
        expect = {}
        ctxt = context.NeutronLoadBalancerContext()()
        self.assertEqual(expect, ctxt)
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        expect = {'load_balancer_name': 'FAKENAME',
                  'load_balancer_base_url': 'http://1.2.3.4:1234'}
        self.test_relation.set({'name': json.dumps('FAKENAME'),
                                'base_url': json.dumps('http://1.2.3.4:1234')})
        ctxt = context.NeutronLoadBalancerContext()()
        self.assertEqual(expect, ctxt)
        expect = {}
        self.test_relation.set({'name': None,
                                'base_url': 'http://1.2.3.4:1234'})
        ctxt = context.NeutronLoadBalancerContext()()
        self.assertEqual(expect, ctxt)
        expect = {}
        self.test_relation.set({'name': 'FAKENAME',
                                'base_url': 'http://1.2.3.4:1234'})
        with self.assertRaises(ValueError):
            context.NeutronLoadBalancerContext()()


class NeutronInfobloxContextTest(CharmTestCase):

    def setUp(self):
        super(NeutronInfobloxContextTest, self).setUp(context, TO_PATCH)
        self.relation_get.side_effect = self.test_relation.get
        self.config.side_effect = self.test_config.get

    def tearDown(self):
        super(NeutronInfobloxContextTest, self).tearDown()

    def test_infoblox_no_related_units(self):
        self.related_units.return_value = []
        ctxt = context.NeutronInfobloxContext()()
        expect = {}

        self.assertEqual(expect, ctxt)

    def test_infoblox_related_units(self):
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        self.test_relation.set(
            {'dc_id': '0',
             'grid_master_host': 'foo',
             'grid_master_name': 'bar',
             'admin_user_name': 'faz',
             'admin_password': 'baz'})
        ctxt = context.NeutronInfobloxContext()()
        expect = {'enable_infoblox': True,
                  'cloud_data_center_id': '0',
                  'grid_master_host': 'foo',
                  'grid_master_name': 'bar',
                  'infoblox_admin_user_name': 'faz',
                  'infoblox_admin_password': 'baz',
                  'wapi_version': '2.3',
                  'wapi_max_results': '-50000',
                  'wapi_paging': True}

        self.assertEqual(expect, ctxt)

    def test_infoblox_related_units_missing_data(self):
        self.related_units.return_value = ['unit1']
        self.relation_ids.return_value = ['rid1']
        self.test_relation.set(
            {'dc_id': '0',
             'grid_master_host': 'foo'})
        ctxt = context.NeutronInfobloxContext()()
        expect = {}

        self.assertEqual(expect, ctxt)
