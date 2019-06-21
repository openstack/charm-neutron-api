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

import sys

from mock import MagicMock, patch, call
from test_utils import CharmTestCase

# python-apt is not installed as part of test-requirements but is imported by
# some charmhelpers modules so create a fake import.
sys.modules['apt'] = MagicMock()

with patch('charmhelpers.core.hookenv.config') as config:
    config.return_value = 'neutron'
    import neutron_api_utils as utils

_reg = utils.register_configs
_map = utils.restart_map

utils.register_configs = MagicMock()
utils.restart_map = MagicMock()

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    import neutron_api_hooks as hooks

hooks.hooks._config_save = False

utils.register_configs = _reg
utils.restart_map = _map

TO_PATCH = [
    'api_port',
    'apt_update',
    'apt_install',
    'config',
    'CONFIGS',
    'check_call',
    'add_source',
    'configure_installation_source',
    'determine_packages',
    'determine_ports',
    'do_openstack_upgrade',
    'dvr_router_present',
    'local_unit',
    'l3ha_router_present',
    'execd_preinstall',
    'filter_installed_packages',
    'get_dns_domain',
    'get_dvr',
    'get_l3ha',
    'get_l2population',
    'get_overlay_network_type',
    'is_clustered',
    'is_leader',
    'is_elected_leader',
    'is_qos_requested_and_valid',
    'is_vlan_trunking_requested_and_valid',
    'log',
    'migrate_neutron_database',
    'neutron_ready',
    'open_port',
    'openstack_upgrade_available',
    'os_release',
    'relation_get',
    'relation_ids',
    'relation_set',
    'related_units',
    'unit_get',
    'update_nrpe_config',
    'service_reload',
    'neutron_plugin_attribute',
    'IdentityServiceContext',
    'force_etcd_restart',
    'status_set',
    'get_relation_ip',
    'generate_ha_relation_data',
    'is_nsg_logging_enabled',
    'is_nfg_logging_enabled',
    'remove_old_packages',
    'services',
    'service_restart',
    'is_db_initialised',
]
NEUTRON_CONF_DIR = "/etc/neutron"

NEUTRON_CONF = '%s/neutron.conf' % NEUTRON_CONF_DIR

from random import randrange


def _mock_nuage_npa(plugin, attr, net_manager=None):
    plugins = {
        'vsp': {
            'config': '/etc/neutron/plugins/nuage/nuage_plugin.ini',
            'driver': 'neutron.plugins.nuage.plugin.NuagePlugin',
            'contexts': [],
            'services': [],
            'packages': [],
            'server_packages': ['neutron-server',
                                'neutron-plugin-nuage'],
            'server_services': ['neutron-server']
        },
    }
    return plugins[plugin][attr]


class DummyContext():

    def __init__(self, return_value):
        self.return_value = return_value

    def __call__(self):
        return self.return_value


class NeutronAPIHooksTests(CharmTestCase):

    def setUp(self):
        super(NeutronAPIHooksTests, self).setUp(hooks, TO_PATCH)

        self.config.side_effect = self.test_config.get
        self.relation_get.side_effect = self.test_relation.get
        self.test_config.set('openstack-origin', 'distro')
        self.test_config.set('neutron-plugin', 'ovs')
        self.neutron_plugin_attribute.side_effect = _mock_nuage_npa
        self.is_nsg_logging_enabled.return_value = False
        self.is_nfg_logging_enabled.return_value = False

    def _fake_relids(self, rel_name):
        return [randrange(100) for _count in range(2)]

    def _call_hook(self, hookname):
        hooks.hooks.execute([
            'hooks/{}'.format(hookname)])

    def test_install_hook(self):
        _pkgs = ['foo', 'bar']
        _ports = [80, 81, 82]
        _port_calls = [call(port) for port in _ports]
        self.determine_packages.return_value = _pkgs
        self.determine_ports.return_value = _ports
        self._call_hook('install')
        self.configure_installation_source.assert_called_with(
            'distro'
        )
        self.apt_update.assert_called_with(fatal=True)
        self.apt_install.assert_has_calls([
            call(_pkgs, fatal=True),
        ])
        self.open_port.assert_has_calls(_port_calls)
        self.assertTrue(self.execd_preinstall.called)

    def test_nuage_install_hook(self):
        self.test_config.set('neutron-plugin', 'vsp')
        self.test_config.set('extra-source',
                             "deb http://10.14.4.1/nuage trusty main")
        _pkgs = ['foo', 'bar', 'python-nuagenetlib']
        _expected_pkgs = list(_pkgs)
        _ports = [80, 81, 82]
        _port_calls = [call(port) for port in _ports]
        self.determine_packages.return_value = _pkgs
        self.determine_ports.return_value = _ports
        self._call_hook('install')
        self.configure_installation_source.assert_called_with(
            'distro'
        )
        self.apt_update.assert_called_with(fatal=True)
        self.apt_install.assert_has_calls([
            call(_expected_pkgs, fatal=True),
        ])
        self.open_port.assert_has_calls(_port_calls)
        self.assertTrue(self.execd_preinstall.called)

    @patch.object(hooks, 'configure_https')
    def test_config_changed(self, conf_https):
        self.neutron_ready.return_value = True
        self.openstack_upgrade_available.return_value = True
        self.dvr_router_present.return_value = False
        self.l3ha_router_present.return_value = False
        self.relation_ids.side_effect = self._fake_relids
        _n_api_rel_joined = self.patch('neutron_api_relation_joined')
        _n_plugin_api_rel_joined =\
            self.patch('neutron_plugin_api_relation_joined')
        _amqp_rel_joined = self.patch('amqp_joined')
        _id_rel_joined = self.patch('identity_joined')
        _id_cluster_joined = self.patch('cluster_joined')
        _id_ha_joined = self.patch('ha_joined')
        self._call_hook('config-changed')
        self.assertTrue(_n_api_rel_joined.called)
        self.assertTrue(_n_plugin_api_rel_joined.called)
        self.assertTrue(_amqp_rel_joined.called)
        self.assertTrue(_id_rel_joined.called)
        self.assertTrue(_id_cluster_joined.called)
        self.assertTrue(_id_ha_joined.called)
        self.assertTrue(self.CONFIGS.write_all.called)
        self.assertTrue(self.do_openstack_upgrade.called)
        self.assertTrue(self.apt_install.called)

    def test_config_changed_nodvr_disprouters(self):
        self.neutron_ready.return_value = True
        self.dvr_router_present.return_value = True
        self.get_dvr.return_value = False
        with self.assertRaises(Exception):
            self._call_hook('config-changed')

    def test_config_changed_nol3ha_harouters(self):
        self.neutron_ready.return_value = True
        self.dvr_router_present.return_value = False
        self.l3ha_router_present.return_value = True
        self.get_l3ha.return_value = False
        with self.assertRaises(Exception):
            self._call_hook('config-changed')

    def test_config_changed_with_openstack_upgrade_action(self):
        self.remove_old_packages.return_value = False
        self.openstack_upgrade_available.return_value = True
        self.test_config.set('action-managed-upgrade', True)

        self._call_hook('config-changed')

        self.assertFalse(self.do_openstack_upgrade.called)

    def test_config_changed_with_purge(self):
        self.remove_old_packages.return_value = True
        self.services.return_value = ['neutron-server']
        self.openstack_upgrade_available.return_value = False
        self._call_hook('config-changed')
        self.remove_old_packages.assert_called_once_with()
        self.service_restart.assert_called_once_with('neutron-server')

    def test_amqp_joined(self):
        self._call_hook('amqp-relation-joined')
        self.relation_set.assert_called_with(
            username='neutron',
            vhost='openstack',
            relation_id=None
        )

    @patch.object(hooks, 'neutron_plugin_api_subordinate_relation_joined')
    def test_amqp_changed(self, plugin_joined):
        self.relation_ids.return_value = ['neutron-plugin-api-subordinate:1']
        self.CONFIGS.complete_contexts.return_value = ['amqp']
        self._call_hook('amqp-relation-changed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))
        self.relation_ids.assert_called_with('neutron-plugin-api-subordinate')
        plugin_joined.assert_called_with(
            relid='neutron-plugin-api-subordinate:1')

    def test_amqp_departed(self):
        self._call_hook('amqp-relation-departed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    def test_db_joined(self):
        self.get_relation_ip.return_value = '10.0.0.1'
        self._call_hook('shared-db-relation-joined')
        self.relation_set.assert_called_with(
            username='neutron',
            database='neutron',
            hostname='10.0.0.1',
        )

    def test_db_joined_spaces(self):
        self.get_relation_ip.return_value = '192.168.20.1'
        self.unit_get.return_value = 'myhostname'
        self._call_hook('shared-db-relation-joined')
        self.relation_set.assert_called_with(
            username='neutron',
            database='neutron',
            hostname='192.168.20.1',
        )

    @patch.object(hooks, 'neutron_plugin_api_subordinate_relation_joined')
    @patch.object(hooks, 'conditional_neutron_migration')
    def test_shared_db_changed(self, cond_neutron_mig, plugin_joined):
        self.CONFIGS.complete_contexts.return_value = ['shared-db']
        self.relation_ids.return_value = ['neutron-plugin-api-subordinate:1']
        self._call_hook('shared-db-relation-changed')
        self.assertTrue(self.CONFIGS.write_all.called)
        cond_neutron_mig.assert_called_with()
        self.relation_ids.assert_called_with('neutron-plugin-api-subordinate')
        plugin_joined.assert_called_with(
            relid='neutron-plugin-api-subordinate:1')

    def test_shared_db_changed_partial_ctxt(self):
        self.CONFIGS.complete_contexts.return_value = []
        self._call_hook('shared-db-relation-changed')
        self.assertFalse(self.CONFIGS.write_all.called)

    def test_amqp_broken(self):
        self._call_hook('amqp-relation-broken')
        self.assertTrue(self.CONFIGS.write_all.called)

    @patch.object(hooks, 'canonical_url')
    def test_identity_joined(self, _canonical_url):
        _canonical_url.return_value = 'http://127.0.0.1'
        self.api_port.return_value = '9696'
        self.test_config.set('region', 'region1')
        _neutron_url = 'http://127.0.0.1:9696'
        _endpoints = {
            'neutron_service': 'neutron',
            'neutron_region': 'region1',
            'neutron_public_url': _neutron_url,
            'neutron_admin_url': _neutron_url,
            'neutron_internal_url': _neutron_url,
            'quantum_service': None,
            'quantum_region': None,
            'quantum_public_url': None,
            'quantum_admin_url': None,
            'quantum_internal_url': None,
        }
        self._call_hook('identity-service-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            relation_settings=_endpoints
        )

    def test_identity_joined_partial_cluster(self):
        self.is_clustered.return_value = False
        self.test_config.set('vip', '10.0.0.10')
        hooks.identity_joined()
        self.assertFalse(self.relation_set.called)

    @patch('charmhelpers.contrib.openstack.ip.service_name',
           lambda *args: 'neutron-api')
    @patch('charmhelpers.contrib.openstack.ip.unit_get')
    @patch('charmhelpers.contrib.openstack.ip.is_clustered')
    @patch('charmhelpers.contrib.openstack.ip.config')
    def test_identity_changed_public_name(self, _config, _is_clustered,
                                          _unit_get):
        _unit_get.return_value = '127.0.0.1'
        _is_clustered.return_value = False
        _config.side_effect = self.test_config.get
        self.api_port.return_value = '9696'
        self.test_config.set('region', 'region1')
        self.test_config.set('os-public-hostname',
                             'neutron-api.example.com')
        self._call_hook('identity-service-relation-joined')
        _neutron_url = 'http://127.0.0.1:9696'
        _endpoints = {
            'neutron_service': 'neutron',
            'neutron_region': 'region1',
            'neutron_public_url': 'http://neutron-api.example.com:9696',
            'neutron_admin_url': _neutron_url,
            'neutron_internal_url': _neutron_url,
            'quantum_service': None,
            'quantum_region': None,
            'quantum_public_url': None,
            'quantum_admin_url': None,
            'quantum_internal_url': None,
        }
        self.relation_set.assert_called_with(
            relation_id=None,
            relation_settings=_endpoints
        )

    def test_identity_changed_partial_ctxt(self):
        self.CONFIGS.complete_contexts.return_value = []
        _api_rel_joined = self.patch('neutron_api_relation_joined')
        self.relation_ids.side_effect = self._fake_relids
        self._call_hook('identity-service-relation-changed')
        self.assertFalse(_api_rel_joined.called)

    @patch.object(hooks, 'configure_https')
    def test_identity_changed(self, conf_https):
        self.CONFIGS.complete_contexts.return_value = ['identity-service']
        _api_rel_joined = self.patch('neutron_api_relation_joined')
        self.relation_ids.side_effect = self._fake_relids
        self._call_hook('identity-service-relation-changed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))
        self.assertTrue(_api_rel_joined.called)

    @patch.object(hooks, 'canonical_url')
    def test_neutron_api_relation_no_id_joined(self, _canonical_url):
        host = 'http://127.0.0.1'
        port = 1234
        _id_rel_joined = self.patch('identity_joined')
        self.relation_ids.side_effect = self._fake_relids
        _canonical_url.return_value = host
        self.api_port.return_value = port
        self.get_dns_domain.return_value = "dnsdomain."
        neutron_url = '%s:%s' % (host, port)
        _relation_data = {
            'enable-sriov': False,
            'neutron-plugin': 'ovs',
            'neutron-url': neutron_url,
            'neutron-security-groups': 'no',
            'neutron-api-ready': 'no',
            'dns-domain': 'dnsdomain.',
        }
        self._call_hook('neutron-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )
        self.assertTrue(_id_rel_joined.called)
        self.test_config.set('neutron-security-groups', True)
        self._call_hook('neutron-api-relation-joined')
        _relation_data['neutron-security-groups'] = 'yes'
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    @patch.object(hooks, 'is_api_ready')
    @patch.object(hooks, 'canonical_url')
    def test_neutron_api_relation_joined(self, _canonical_url, api_ready):
        api_ready.return_value = True
        host = 'http://127.0.0.1'
        port = 1234
        _canonical_url.return_value = host
        self.api_port.return_value = port
        self.get_dns_domain.return_value = ""
        neutron_url = '%s:%s' % (host, port)
        _relation_data = {
            'enable-sriov': False,
            'neutron-plugin': 'ovs',
            'neutron-url': neutron_url,
            'neutron-security-groups': 'no',
            'neutron-api-ready': 'yes',
        }
        self._call_hook('neutron-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_vsd_api_relation_changed(self):
        self.os_release.return_value = 'kilo'
        self.test_config.set('neutron-plugin', 'vsp')
        self.test_relation.set({
            'vsd-ip-address': '10.11.12.13',
            'nuage-cms-id': 'abc'
        })
        self._call_hook('vsd-rest-api-relation-changed')
        config_file = '/etc/neutron/plugins/nuage/nuage_plugin.ini'
        self.assertTrue(self.CONFIGS.write.called_with(config_file))

    def test_vsd_api_relation_joined(self):
        self.os_release.return_value = 'kilo'
        repo = 'cloud:trusty-kilo'
        self.test_config.set('openstack-origin', repo)
        self._call_hook('vsd-rest-api-relation-joined')
        e = "Neutron Api hook failed as vsd-cms-name" \
            " is not specified"
        self.status_set.assert_called_with(
            'blocked', e)
        self.test_config.set('vsd-cms-name', '1234567890')
        _relation_data = {
            'vsd-cms-name': '1234567890',
        }
        self._call_hook('vsd-rest-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_api_relation_changed(self):
        self.CONFIGS.complete_contexts.return_value = ['shared-db']
        self._call_hook('neutron-api-relation-changed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    def test_neutron_api_relation_changed_incomplere_ctxt(self):
        self.CONFIGS.complete_contexts.return_value = []
        self._call_hook('neutron-api-relation-changed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    @patch.object(hooks, 'is_api_ready')
    def test_neutron_load_balancer_relation_joined(self, is_api_ready):
        is_api_ready.return_value = True
        self._call_hook('neutron-load-balancer-relation-joined')
        is_api_ready.assert_called_once_with(self.CONFIGS)
        _relation_data = {'neutron-api-ready': True}
        self.relation_set.assert_called_once_with(relation_id=None,
                                                  **_relation_data)

    @patch.object(hooks, 'is_api_ready')
    def test_neutron_load_balancer_relation_changed(self, is_api_ready):
        is_api_ready.return_value = True
        self._call_hook('neutron-load-balancer-relation-changed')
        is_api_ready.assert_called_once_with(self.CONFIGS)
        _relation_data = {'neutron-api-ready': True}
        self.relation_set.assert_called_once_with(relation_id=None,
                                                  **_relation_data)
        self.CONFIGS.write.assert_called_once_with(NEUTRON_CONF)

    def test_neutron_plugin_api_relation_joined_nol2(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': False,
            'enable-l3ha': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': False,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }
        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = False
        self.get_l3ha.return_value = False
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''
        self._call_hook('neutron-plugin-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_plugin_api_relation_joined_nsg_logging(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': False,
            'enable-l3ha': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': True,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }

        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = False
        self.get_l3ha.return_value = False
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''

        self.test_config.set('enable-security-group-logging', True)
        self.is_nsg_logging_enabled.return_value = True

        self._call_hook('neutron-plugin-api-relation-joined')

        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_plugin_api_relation_joined_nfg_logging(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': False,
            'enable-l3ha': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': False,
            'enable-nfg-logging': True,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }

        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = False
        self.get_l3ha.return_value = False
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''

        self.test_config.set('enable-firewall-group-logging', True)
        self.is_nfg_logging_enabled.return_value = True

        self._call_hook('neutron-plugin-api-relation-joined')

        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data)

    def test_neutron_plugin_api_relation_joined_dvr(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': True,
            'enable-l3ha': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': True,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': False,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }
        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = True
        self.get_l3ha.return_value = False
        self.get_l2population.return_value = True
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''
        self._call_hook('neutron-plugin-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_plugin_api_relation_joined_l3ha(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': False,
            'enable-l3ha': True,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': False,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }
        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = False
        self.get_l3ha.return_value = True
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''
        self._call_hook('neutron-plugin-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_plugin_api_relation_joined_w_mtu(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        self.test_config.set('network-device-mtu', 1500)
        _relation_data = {
            'neutron-security-groups': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'overlay-network-type': 'vxlan',
            'network-device-mtu': 1500,
            'enable-l3ha': True,
            'enable-dvr': True,
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'enable-nsg-logging': False,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }
        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = True
        self.get_l3ha.return_value = True
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = ''
        self._call_hook('neutron-plugin-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    def test_neutron_plugin_api_relation_joined_dns(self):
        self.unit_get.return_value = '172.18.18.18'
        self.IdentityServiceContext.return_value = \
            DummyContext(return_value={})
        _relation_data = {
            'neutron-security-groups': False,
            'enable-dvr': False,
            'enable-l3ha': False,
            'enable-qos': False,
            'enable-vlan-trunking': False,
            'addr': '172.18.18.18',
            'polling-interval': 2,
            'rpc-response-timeout': 60,
            'report-interval': 30,
            'l2-population': False,
            'overlay-network-type': 'vxlan',
            'service_protocol': None,
            'auth_protocol': None,
            'service_tenant': None,
            'service_port': None,
            'region': 'RegionOne',
            'service_password': None,
            'auth_port': None,
            'auth_host': None,
            'service_username': None,
            'service_host': None,
            'neutron-api-ready': 'no',
            'dns-domain': 'openstack.example.',
            'enable-nsg-logging': False,
            'enable-nfg-logging': False,
            'global-physnet-mtu': 1500,
            'physical-network-mtus': None,
        }
        self.is_qos_requested_and_valid.return_value = False
        self.is_vlan_trunking_requested_and_valid.return_value = False
        self.get_dvr.return_value = False
        self.get_l3ha.return_value = False
        self.get_l2population.return_value = False
        self.get_overlay_network_type.return_value = 'vxlan'
        self.get_dns_domain.return_value = 'openstack.example.'
        self._call_hook('neutron-plugin-api-relation-joined')
        self.relation_set.assert_called_with(
            relation_id=None,
            **_relation_data
        )

    @patch.object(hooks, 'check_local_db_actions_complete')
    def test_cluster_changed(self, mock_check_local_db_actions_complete):
        self._call_hook('cluster-relation-changed')
        self.assertTrue(self.CONFIGS.write_all.called)
        self.assertTrue(mock_check_local_db_actions_complete.called)

    def test_ha_relation_joined(self):
        self.generate_ha_relation_data.return_value = {'rel_data': 'data'}
        self._call_hook('ha-relation-joined')
        self.relation_set.assert_called_once_with(
            relation_id=None, rel_data='data')

    def test_ha_changed(self):
        self.test_relation.set({
            'clustered': 'true',
        })
        self.relation_ids.side_effect = self._fake_relids
        _n_api_rel_joined = self.patch('neutron_api_relation_joined')
        _id_rel_joined = self.patch('identity_joined')
        self._call_hook('ha-relation-changed')
        self.assertTrue(_n_api_rel_joined.called)
        self.assertTrue(_id_rel_joined.called)

    def test_ha_changed_not_clustered(self):
        self.test_relation.set({
            'clustered': None,
        })
        self.relation_ids.side_effect = self._fake_relids
        _n_api_rel_joined = self.patch('neutron_api_relation_joined')
        _id_rel_joined = self.patch('identity_joined')
        self._call_hook('ha-relation-changed')
        self.assertFalse(_n_api_rel_joined.called)
        self.assertFalse(_id_rel_joined.called)

    def test_configure_https(self):
        self.CONFIGS.complete_contexts.return_value = ['https']
        self.relation_ids.side_effect = self._fake_relids
        _id_rel_joined = self.patch('identity_joined')
        hooks.configure_https()
        self.check_call.assert_called_with(['a2ensite',
                                            'openstack_https_frontend'])
        self.assertTrue(_id_rel_joined.called)

    def test_configure_https_nohttps(self):
        self.CONFIGS.complete_contexts.return_value = []
        self.relation_ids.side_effect = self._fake_relids
        _id_rel_joined = self.patch('identity_joined')
        hooks.configure_https()
        self.check_call.assert_called_with(['a2dissite',
                                            'openstack_https_frontend'])
        self.assertTrue(_id_rel_joined.called)

    def test_conditional_neutron_migration_leader(self):
        self.test_relation.set({
            'allowed_units': 'neutron-api/0 neutron-api/1 neutron-api/4',
        })
        self.local_unit.return_value = 'neutron-api/1'
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'kilo'
        hooks.conditional_neutron_migration()
        self.migrate_neutron_database.assert_called()

    def test_conditional_neutron_migration_leader_icehouse(self):
        self.test_relation.set({
            'allowed_units': 'neutron-api/0 neutron-api/1 neutron-api/4',
        })
        self.local_unit.return_value = 'neutron-api/1'
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'icehouse'
        hooks.conditional_neutron_migration()
        self.assertFalse(self.migrate_neutron_database.called)

    def test_conditional_neutron_migration_notleader(self):
        self.is_elected_leader.return_value = False
        self.os_release.return_value = 'icehouse'
        hooks.conditional_neutron_migration()
        self.assertFalse(self.migrate_neutron_database.called)

    def test_etcd_peer_joined(self):
        self._call_hook('etcd-proxy-relation-joined')
        self.assertTrue(self.CONFIGS.register.called)
        self.CONFIGS.write.assert_any_call('/etc/init/etcd.conf')
        self.CONFIGS.write.assert_any_call('/etc/default/etcd')

    def test_designate_peer_joined(self):
        self.test_relation.set({
            'endpoint': 'http://1.2.3.4:9001',
        })
        self.relation_ids.side_effect = self._fake_relids
        self._call_hook('external-dns-relation-joined')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    def test_designate_peer_departed(self):
        self._call_hook('external-dns-relation-departed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    def test_infoblox_peer_changed(self):
        self.is_db_initialised.return_value = True
        self.test_relation.set({
            'dc_id': '0',
        })
        self.os_release.return_value = 'queens'
        self.relation_ids.side_effect = self._fake_relids
        self._call_hook('infoblox-neutron-relation-changed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))

    def test_infoblox_peer_departed(self):
        self._call_hook('infoblox-neutron-relation-departed')
        self.assertTrue(self.CONFIGS.write.called_with(NEUTRON_CONF))
