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

from mock import MagicMock, patch, call
from collections import OrderedDict
from copy import deepcopy

import charmhelpers.contrib.openstack.templating as templating
import charmhelpers.contrib.openstack.utils
import charmhelpers.core.hookenv as hookenv
import neutron_api_context as ncontext

templating.OSConfigRenderer = MagicMock()

with patch('charmhelpers.core.hookenv.config') as config:
    config.return_value = 'neutron'
    import neutron_api_utils as nutils

from test_utils import (
    CharmTestCase,
    patch_open,
)


TO_PATCH = [
    'apt_install',
    'apt_update',
    'apt_upgrade',
    'apt_purge',
    'apt_autoremove',
    'filter_missing_packages',
    'add_source',
    'b64encode',
    'config',
    'configure_installation_source',
    'get_os_codename_install_source',
    'log',
    'lsb_release',
    'neutron_plugin_attribute',
    'os_release',
    'service_restart',
    'subprocess',
    'is_elected_leader',
    'service_stop',
    'service_start',
    'glob',
    'os_application_version_set',
]


def _mock_npa(plugin, attr, net_manager=None):
    plugins = {
        'ovs': {
            'config': '/etc/neutron/plugins/ml2/ml2_conf.ini',
            'driver': 'neutron.plugins.ml2.plugin.Ml2Plugin',
            'contexts': [],
            'services': ['neutron-plugin-openvswitch-agent'],
            'packages': [['neutron-plugin-openvswitch-agent']],
            'server_packages': ['neutron-server',
                                'neutron-plugin-ml2'],
            'server_services': ['neutron-server']
        },
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


class DummyIdentityServiceContext():

    def __init__(self, return_value):
        self.return_value = return_value

    def __call__(self):
        return self.return_value


class TestNeutronAPIUtils(CharmTestCase):
    def setUp(self):
        super(TestNeutronAPIUtils, self).setUp(nutils, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.test_config.set('region', 'region101')
        self.neutron_plugin_attribute.side_effect = _mock_npa

    def tearDown(self):
        # Reset cached cache
        hookenv.cache = {}

    def test_api_port(self):
        port = nutils.api_port('neutron-server')
        self.assertEqual(port, nutils.API_PORTS['neutron-server'])

    def test_determine_packages(self):
        self.os_release.return_value = 'havana'
        self.get_os_codename_install_source.return_value = 'havana'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-ml2'])
        self.assertEqual(sorted(pkg_list), sorted(expect))

    def test_determine_vsp_packages(self):
        self.os_release.return_value = 'havana'
        self.test_config.set('nuage-packages',
                             'python-nuagenetlib nuage-neutron')
        self.test_config.set('neutron-plugin', 'vsp')
        self.get_os_codename_install_source.return_value = 'juno'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-nuage',
                       'python-nuagenetlib', 'nuage-neutron'])
        self.assertEqual(sorted(pkg_list), sorted(expect))

    def test_determine_packages_kilo(self):
        self.os_release.return_value = 'havana'
        self.get_os_codename_install_source.return_value = 'kilo'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-ml2',
                      'python-networking-hyperv'])
        expect.extend(nutils.KILO_PACKAGES)
        self.assertEqual(sorted(pkg_list), sorted(expect))

    def test_determine_packages_train(self):
        self.os_release.return_value = 'train'
        self.get_os_codename_install_source.return_value = 'train'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend([
            'memcached',
            'neutron-server',
            'neutron-plugin-ml2',
            'python-networking-hyperv'
        ])
        expect.extend(nutils.KILO_PACKAGES)
        expect = [p for p in expect if not p.startswith('python-')]
        expect.extend(nutils.PY3_PACKAGES)
        expect.remove('python3-neutron-lbaas')
        self.assertEqual(sorted(pkg_list), sorted(expect))

    @patch.object(nutils.neutron_api_context, 'NeutronApiSDNContext')
    def test_determine_packages_noplugin(self, _NeutronApiSDNContext):
        self.os_release.return_value = 'havana'
        self.get_os_codename_install_source.return_value = 'havana'
        self.test_config.set('manage-neutron-plugin-legacy-mode', False)
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server'])
        self.assertEqual(sorted(pkg_list), sorted(expect))

    def test_determine_ports(self):
        self.os_release.return_value = 'havana'
        port_list = nutils.determine_ports()
        self.assertEqual(port_list, [9696])

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map(self, _path_exists, _manage_plugin):
        self.os_release.return_value = 'havana'
        _path_exists.return_value = False
        _manage_plugin.return_value = True
        _map = nutils.resource_map()
        confs = [nutils.NEUTRON_CONF, nutils.NEUTRON_DEFAULT,
                 nutils.APACHE_CONF]
        [self.assertIn(q_conf, _map.keys()) for q_conf in confs]
        self.assertTrue(nutils.APACHE_24_CONF not in _map.keys())

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map_liberty(self, _path_exists, _manage_plugin):
        _path_exists.return_value = False
        _manage_plugin.return_value = True
        self.os_release.return_value = 'liberty'
        _map = nutils.resource_map()
        confs = [nutils.NEUTRON_CONF, nutils.NEUTRON_DEFAULT,
                 nutils.APACHE_CONF, nutils.NEUTRON_LBAAS_CONF,
                 nutils.NEUTRON_VPNAAS_CONF]
        [self.assertIn(q_conf, _map.keys()) for q_conf in confs]
        self.assertTrue(nutils.APACHE_24_CONF not in _map.keys())

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map_queens(self, _path_exists, _manage_plugin):
        _path_exists.return_value = False
        _manage_plugin.return_value = True
        self.os_release.return_value = 'queens'
        _map = nutils.resource_map()
        confs = [nutils.NEUTRON_CONF, nutils.NEUTRON_DEFAULT,
                 nutils.APACHE_CONF, nutils.NEUTRON_LBAAS_CONF,
                 nutils.NEUTRON_VPNAAS_CONF]
        [self.assertIn(q_conf, _map.keys()) for q_conf in confs]
        self.assertTrue(nutils.APACHE_24_CONF not in _map.keys())

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map_apache24(self, _path_exists, _manage_plugin):
        self.os_release.return_value = 'havana'
        _path_exists.return_value = True
        _manage_plugin.return_value = True
        _map = nutils.resource_map()
        confs = [nutils.NEUTRON_CONF, nutils.NEUTRON_DEFAULT,
                 nutils.APACHE_24_CONF]
        [self.assertIn(q_conf, _map.keys()) for q_conf in confs]
        self.assertTrue(nutils.APACHE_CONF not in _map.keys())

    @patch.object(nutils.neutron_api_context, 'NeutronApiSDNContext')
    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map_noplugin(self,
                                   _path_exists,
                                   _manage_plugin,
                                   _NeutronApiSDNContext):
        self.os_release.return_value = 'havana'
        _path_exists.return_value = True
        _manage_plugin.return_value = False
        _map = nutils.resource_map()
        found_sdn_ctxt = False
        found_sdnconfig_ctxt = False
        for ctxt in _map[nutils.NEUTRON_CONF]['contexts']:
            if isinstance(ctxt, MagicMock):
                found_sdn_ctxt = True
        for ctxt in _map[nutils.NEUTRON_DEFAULT]['contexts']:
            if isinstance(ctxt, ncontext.NeutronApiSDNConfigFileContext):
                found_sdnconfig_ctxt = True
        self.assertTrue(found_sdn_ctxt and found_sdnconfig_ctxt)

    @patch('os.path.exists')
    def test_restart_map(self, mock_path_exists):
        self.os_release.return_value = 'havana'
        mock_path_exists.return_value = False
        _restart_map = nutils.restart_map()
        ML2CONF = "/etc/neutron/plugins/ml2/ml2_conf.ini"
        expect = OrderedDict([
            (nutils.NEUTRON_CONF, ['neutron-server']),
            (nutils.NEUTRON_DEFAULT, ['neutron-server']),
            (nutils.API_PASTE_INI, ['neutron-server']),
            (nutils.APACHE_CONF, ['apache2']),
            (nutils.HAPROXY_CONF, ['haproxy']),
            (ML2CONF, ['neutron-server']),
        ])
        self.assertEqual(_restart_map, expect)

    @patch.object(nutils.os.path, 'isdir')
    @patch.object(nutils.os.path, 'exists')
    def test_restart_map_ssl(self, mock_path_exists, mock_path_isdir):
        self.os_release.return_value = 'havana'
        mock_path_exists.return_value = False
        mock_path_isdir.return_value = True
        _restart_map = nutils.restart_map()
        ML2CONF = "/etc/neutron/plugins/ml2/ml2_conf.ini"
        expect = OrderedDict([
            (nutils.NEUTRON_CONF, ['neutron-server']),
            (nutils.NEUTRON_DEFAULT, ['neutron-server']),
            (nutils.API_PASTE_INI, ['neutron-server']),
            (nutils.APACHE_CONF, ['apache2']),
            (nutils.HAPROXY_CONF, ['haproxy']),
            (ML2CONF, ['neutron-server']),
            ('{}/*'.format(nutils.APACHE_SSL_DIR),
             ['apache2', 'neutron-server']),
        ])
        self.assertEqual(_restart_map, expect)

    @patch('os.path.exists')
    def test_register_configs(self, mock_path_exists):
        self.os_release.return_value = 'havana'
        mock_path_exists.return_value = False

        class _mock_OSConfigRenderer():
            def __init__(self, templates_dir=None, openstack_release=None):
                self.configs = []
                self.ctxts = []

            def register(self, config, ctxt):
                self.configs.append(config)
                self.ctxts.append(ctxt)

        templating.OSConfigRenderer.side_effect = _mock_OSConfigRenderer
        _regconfs = nutils.register_configs()
        confs = ['/etc/neutron/neutron.conf',
                 '/etc/neutron/api-paste.ini',
                 '/etc/default/neutron-server',
                 '/etc/neutron/plugins/ml2/ml2_conf.ini',
                 '/etc/apache2/sites-available/openstack_https_frontend',
                 '/etc/haproxy/haproxy.cfg']
        self.assertEqual(sorted(_regconfs.configs), sorted(confs))

    @patch('os.path.isfile')
    def test_keystone_ca_cert_b64_no_cert_file(self, _isfile):
        _isfile.return_value = False
        cert = nutils.keystone_ca_cert_b64()
        self.assertEqual(cert, None)

    @patch('os.path.isfile')
    def test_keystone_ca_cert_b64(self, _isfile):
        _isfile.return_value = True
        with patch_open() as (_open, _file):
            nutils.keystone_ca_cert_b64()
            self.assertTrue(self.b64encode.called)

    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    def test_do_openstack_upgrade(self,
                                  stamp_neutron_db, migrate_neutron_db,
                                  gsrc):
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'icehouse'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:trusty-juno')
        gsrc.return_value = 'juno'
        self.get_os_codename_install_source.return_value = 'juno'
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.os_release.assert_called_with('neutron-common')
        self.assertTrue(self.log.called)
        self.configure_installation_source.assert_called_with(
            'cloud:trusty-juno'
        )
        self.apt_update.assert_called_with(fatal=True)
        dpkg_opts = [
            '--option', 'Dpkg::Options::=--force-confnew',
            '--option', 'Dpkg::Options::=--force-confdef',
        ]
        self.apt_upgrade.assert_called_with(options=dpkg_opts,
                                            fatal=True,
                                            dist=True)
        pkgs = nutils.determine_packages()
        pkgs.sort()
        self.apt_install.assert_called_with(packages=pkgs,
                                            options=dpkg_opts,
                                            fatal=True)
        configs.set_release.assert_called_with(openstack_release='juno')
        stamp_neutron_db.assert_called_with('icehouse')
        calls = [call(upgrade=True)]
        migrate_neutron_db.assert_has_calls(calls)

    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    def test_do_openstack_upgrade_liberty(self,
                                          stamp_neutron_db, migrate_neutron_db,
                                          gsrc):
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'liberty'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:trusty-mitaka')
        gsrc.return_value = 'mitaka'
        self.get_os_codename_install_source.return_value = 'mitaka'
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.assertFalse(stamp_neutron_db.called)

    @patch.object(nutils, 'fwaas_migrate_v1_to_v2')
    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    def test_do_openstack_upgrade_rocky(self,
                                        stamp_neutron_db,
                                        migrate_neutron_db,
                                        gsrc,
                                        fwaas_migrate_v1_to_v2):
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'rocky'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:bionic-rocky')
        gsrc.return_value = 'rocky'
        self.get_os_codename_install_source.return_value = 'rocky'
        self.filter_missing_packages.return_value = ['python-neutron']
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.apt_purge.assert_called_with(['python-neutron'], fatal=True)
        self.apt_autoremove.assert_called_with(purge=True, fatal=True)
        self.filter_missing_packages.assert_called_with(nutils.PURGE_PACKAGES)
        self.assertFalse(stamp_neutron_db.called)
        fwaas_migrate_v1_to_v2.assert_not_called()
        configs.write_all.assert_called_once_with()

    @patch.object(nutils, 'fwaas_migrate_v1_to_v2')
    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    def test_do_openstack_upgrade_stein(self,
                                        stamp_neutron_db,
                                        migrate_neutron_db,
                                        gsrc,
                                        fwaas_migrate_v1_to_v2):
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'stein'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:bionic-stein')
        gsrc.return_value = 'rocky'
        self.get_os_codename_install_source.return_value = 'stein'
        self.filter_missing_packages.return_value = ['python-neutron']
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.apt_purge.assert_called_with(['python-neutron'], fatal=True)
        self.apt_autoremove.assert_called_with(purge=True, fatal=True)
        self.filter_missing_packages.assert_called_with(nutils.PURGE_PACKAGES)
        self.assertFalse(stamp_neutron_db.called)
        fwaas_migrate_v1_to_v2.assert_called_once_with()
        configs.write_all.assert_called_once_with()

    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    def test_do_openstack_upgrade_notleader(self,
                                            stamp_neutron_db,
                                            migrate_neutron_db,
                                            gsrc):
        self.is_elected_leader.return_value = False
        self.os_release.return_value = 'icehouse'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:trusty-juno')
        gsrc.return_value = 'juno'
        self.get_os_codename_install_source.return_value = 'juno'
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.os_release.assert_called_with('neutron-common')
        self.assertTrue(self.log.called)
        self.configure_installation_source.assert_called_with(
            'cloud:trusty-juno'
        )
        self.apt_update.assert_called_with(fatal=True)
        dpkg_opts = [
            '--option', 'Dpkg::Options::=--force-confnew',
            '--option', 'Dpkg::Options::=--force-confdef',
        ]
        self.apt_upgrade.assert_called_with(options=dpkg_opts,
                                            fatal=True,
                                            dist=True)
        pkgs = nutils.determine_packages()
        pkgs.sort()
        self.apt_install.assert_called_with(packages=pkgs,
                                            options=dpkg_opts,
                                            fatal=True)
        configs.set_release.assert_called_with(openstack_release='juno')
        self.assertFalse(stamp_neutron_db.called)
        self.assertFalse(migrate_neutron_db.called)

    @patch.object(ncontext, 'IdentityServiceContext')
    @patch.object(nutils, 'FakeNeutronClient')
    def test_get_neutron_client(self, nclient, IdentityServiceContext):
        creds = {
            'auth_protocol': 'http',
            'auth_host': 'myhost',
            'auth_port': '2222',
            'admin_user': 'bob',
            'admin_password': 'pa55w0rd',
            'admin_tenant_name': 'tenant1',
            'region': 'region2',
        }
        IdentityServiceContext.return_value = \
            DummyIdentityServiceContext(return_value=creds)
        nutils.get_neutron_client()
        nclient.assert_called_with(
            username='bob',
            tenant_name='tenant1',
            password='pa55w0rd',
            auth_url='http://myhost:2222/v2.0',
            region_name='region2',
        )

    @patch.object(ncontext, 'IdentityServiceContext')
    def test_get_neutron_client_noidservice(self, IdentityServiceContext):
        creds = {}
        IdentityServiceContext.return_value = \
            DummyIdentityServiceContext(return_value=creds)
        self.assertEqual(nutils.get_neutron_client(), None)

    @patch.object(nutils, 'get_neutron_client')
    def test_router_feature_present_keymissing(self, get_neutron_client):
        routers = {
            'routers': [
                {
                    u'status': u'ACTIVE',
                    u'external_gateway_info': {
                        u'network_id': u'eedffb9b-b93e-49c6-9545-47c656c9678e',
                        u'enable_snat': True
                    }, u'name': u'provider-router',
                    u'admin_state_up': True,
                    u'tenant_id': u'b240d06e38394780a3ea296138cdd174',
                    u'routes': [],
                    u'id': u'84182bc8-eede-4564-9c87-1a56bdb26a90',
                }
            ]
        }
        get_neutron_client.list_routers.return_value = routers
        self.assertEqual(nutils.router_feature_present('ha'), False)

    @patch.object(nutils, 'get_neutron_client')
    def test_router_feature_present_keyfalse(self, get_neutron_client):
        routers = {
            'routers': [
                {
                    u'status': u'ACTIVE',
                    u'external_gateway_info': {
                        u'network_id': u'eedffb9b-b93e-49c6-9545-47c656c9678e',
                        u'enable_snat': True
                    }, u'name': u'provider-router',
                    u'admin_state_up': True,
                    u'tenant_id': u'b240d06e38394780a3ea296138cdd174',
                    u'routes': [],
                    u'id': u'84182bc8-eede-4564-9c87-1a56bdb26a90',
                    u'ha': False,
                }
            ]
        }
        dummy_client = MagicMock()
        dummy_client.list_routers.return_value = routers
        get_neutron_client.return_value = dummy_client
        self.assertEqual(nutils.router_feature_present('ha'), False)

    @patch.object(nutils, 'get_neutron_client')
    def test_router_feature_present_keytrue(self, get_neutron_client):
        routers = {
            'routers': [
                {
                    u'status': u'ACTIVE',
                    u'external_gateway_info': {
                        u'network_id': u'eedffb9b-b93e-49c6-9545-47c656c9678e',
                        u'enable_snat': True
                    }, u'name': u'provider-router',
                    u'admin_state_up': True,
                    u'tenant_id': u'b240d06e38394780a3ea296138cdd174',
                    u'routes': [],
                    u'id': u'84182bc8-eede-4564-9c87-1a56bdb26a90',
                    u'ha': True,
                }
            ]
        }

        dummy_client = MagicMock()
        dummy_client.list_routers.return_value = routers
        get_neutron_client.return_value = dummy_client
        self.assertEqual(nutils.router_feature_present('ha'), True)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready(self, get_neutron_client):
        dummy_client = MagicMock()
        dummy_client.list_routers.return_value = []
        get_neutron_client.return_value = dummy_client
        self.assertEqual(nutils.neutron_ready(), True)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready_noclient(self, get_neutron_client):
        get_neutron_client.return_value = None
        self.assertEqual(nutils.neutron_ready(), False)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready_clientexception(self, get_neutron_client):
        dummy_client = MagicMock()
        dummy_client.list_routers.side_effect = Exception('Boom!')
        get_neutron_client.return_value = dummy_client
        self.assertEqual(nutils.neutron_ready(), False)

    def test_stamp_neutron_database(self):
        nutils.stamp_neutron_database('icehouse')
        cmd = ['neutron-db-manage',
               '--config-file', '/etc/neutron/neutron.conf',
               '--config-file', '/etc/neutron/plugins/ml2/ml2_conf.ini',
               'stamp',
               'icehouse']
        self.subprocess.check_output.assert_called_with(cmd)

    @patch.object(nutils, 'relation_set')
    @patch.object(nutils, 'is_db_initialised', lambda: False)
    @patch.object(nutils, 'relation_get')
    @patch.object(nutils, 'local_unit', lambda *args: 'unit/0')
    def test_check_local_db_actions_complete_by_self(self, mock_relation_get,
                                                     mock_relation_set):
        mock_relation_get.return_value = {}
        nutils.check_local_db_actions_complete()
        self.assertFalse(mock_relation_set.called)

        mock_relation_get.return_value = {nutils.NEUTRON_DB_INIT_RKEY:
                                          'unit/0-1234'}
        nutils.check_local_db_actions_complete()
        self.assertFalse(mock_relation_set.called)

    @patch.object(nutils, 'relation_ids')
    @patch.object(nutils, 'relation_set')
    @patch.object(nutils, 'relation_get')
    @patch.object(nutils, 'is_db_initialised')
    @patch.object(nutils, 'local_unit', lambda *args: 'unit/0')
    def test_check_local_db_actions_complete(self,
                                             mock_is_db_initialised,
                                             mock_relation_get,
                                             mock_relation_set,
                                             mock_relation_ids):
        shared_db_rel_id = 'shared-db:1'
        mock_relation_ids.return_value = [shared_db_rel_id]
        mock_is_db_initialised.return_value = True
        r_settings = {}

        def fake_relation_get(unit=None, rid=None, attribute=None):
            if attribute:
                return r_settings.get(attribute)
            else:
                return r_settings

        mock_relation_get.side_effect = fake_relation_get
        nutils.check_local_db_actions_complete()
        self.assertFalse(mock_relation_set.called)
        init_db_val = 'unit/1-{}-1234'.format(shared_db_rel_id)
        r_settings = {nutils.NEUTRON_DB_INIT_RKEY: init_db_val}
        nutils.check_local_db_actions_complete()
        calls = [call(**{nutils.NEUTRON_DB_INIT_ECHO_RKEY: init_db_val})]
        mock_relation_set.assert_has_calls(calls)
        self.service_restart.assert_called_with('neutron-server')

    @patch.object(nutils, 'local_unit')
    @patch.object(nutils, 'relation_get')
    @patch.object(nutils, 'relation_ids')
    @patch.object(nutils, 'related_units')
    def test_is_db_initisalised_false(self, mock_related_units,
                                      mock_relation_ids,
                                      mock_relation_get,
                                      mock_local_unit):
        shared_db_rel_id = 'shared-db:1'
        mock_relation_ids.return_value = [shared_db_rel_id]
        settings = {'0': {}, '1': {}}

        def mock_rel_get(unit=None, rid=None, attribute=None):
            if not unit:
                unit = '0'

            if attribute:
                return settings[unit].get(attribute)

            return settings[unit]

        mock_local_unit.return_value = '0'
        mock_relation_get.side_effect = mock_rel_get
        mock_related_units.return_value = ['1']
        mock_relation_ids.return_value = ['cluster:1']
        self.assertFalse(nutils.is_db_initialised())

    @patch.object(nutils, 'local_unit')
    @patch.object(nutils, 'relation_get')
    @patch.object(nutils, 'relation_ids')
    @patch.object(nutils, 'related_units')
    def test_is_db_initisalised_true(self, mock_related_units,
                                     mock_relation_ids,
                                     mock_relation_get,
                                     mock_local_unit):
        shared_db_rel_id = 'shared-db:1'
        init_db_val = 'unit/1-{}-1234'.format(shared_db_rel_id)
        mock_relation_ids.return_value = [shared_db_rel_id]
        settings = {'0': {nutils.NEUTRON_DB_INIT_RKEY: init_db_val},
                    '1': {nutils.NEUTRON_DB_INIT_ECHO_RKEY: init_db_val}}

        def mock_rel_ids(name):
            if name == 'cluster':
                return 'cluster:1'
            elif name == 'shared-db':
                return 'shared-db:1'

            raise Exception("Uknown relation '{}'".format(name))

        def mock_rel_get(unit=None, rid=None, attribute=None):
            if not unit:
                unit = '0'

            if attribute:
                return settings[unit].get(attribute)

            return settings[unit]

        mock_relation_ids.side_effect = mock_rel_ids
        mock_local_unit.return_value = '0'
        mock_relation_get.side_effect = mock_rel_get
        mock_related_units.return_value = ['1']
        self.assertTrue(nutils.is_db_initialised())

    @patch.object(nutils, 'relation_ids')
    @patch.object(nutils, 'is_db_initialised')
    def test_migrate_neutron_database(self, mock_is_db_initd, mock_rel_ids):
        mock_is_db_initd.return_value = False
        nutils.migrate_neutron_database()
        cmd = ['neutron-db-manage',
               '--config-file', '/etc/neutron/neutron.conf',
               '--config-file', '/etc/neutron/plugins/ml2/ml2_conf.ini',
               'upgrade',
               'head']
        self.subprocess.check_output.assert_called_with(cmd)

    def test_manage_plugin_true(self):
        self.test_config.set('manage-neutron-plugin-legacy-mode', True)
        manage = nutils.manage_plugin()
        self.assertTrue(manage)

    def test_manage_plugin_false(self):
        self.test_config.set('manage-neutron-plugin-legacy-mode', False)
        manage = nutils.manage_plugin()
        self.assertFalse(manage)

    def test_additional_install_locations_calico(self):
        self.get_os_codename_install_source.return_value = 'icehouse'
        nutils.additional_install_locations('Calico', '')
        self.add_source.assert_called_with('ppa:project-calico/icehouse')

    def test_unusual_calico_install_location(self):
        self.test_config.set('calico-origin', 'ppa:testppa/project-calico')
        nutils.additional_install_locations('Calico', '')
        self.add_source.assert_called_with('ppa:testppa/project-calico')

    def test_follows_openstack_origin(self):
        self.get_os_codename_install_source.return_value = 'juno'
        nutils.additional_install_locations('Calico', 'cloud:trusty-juno')
        self.add_source.assert_called_with('ppa:project-calico/juno')

    def test_calico_source_liberty(self):
        self.get_os_codename_install_source.return_value = 'liberty'
        nutils.additional_install_locations('Calico', '')
        self.add_source.assert_called_with('ppa:project-calico/calico-1.4')

    @patch('shutil.rmtree')
    def test_force_etcd_restart(self, rmtree):
        self.glob.glob.return_value = [
            '/var/lib/etcd/one', '/var/lib/etcd/two'
        ]
        nutils.force_etcd_restart()
        self.service_stop.assert_called_once_with('etcd')
        self.glob.glob.assert_called_once_with('/var/lib/etcd/*')
        rmtree.assert_any_call('/var/lib/etcd/one')
        rmtree.assert_any_call('/var/lib/etcd/two')
        self.service_start.assert_called_once_with('etcd')

    def _test_is_api_ready(self, tgt):
        fake_config = MagicMock()
        with patch.object(nutils, 'incomplete_relation_data') as ird:
            ird.return_value = (not tgt)
            self.assertEqual(nutils.is_api_ready(fake_config), tgt)
            ird.assert_called_with(
                fake_config, nutils.REQUIRED_INTERFACES)

    def test_is_api_ready_true(self):
        self._test_is_api_ready(True)

    def test_is_api_ready_false(self):
        self._test_is_api_ready(False)

    def test_assess_status(self):
        with patch.object(nutils, 'assess_status_func') as asf:
            callee = MagicMock()
            asf.return_value = callee
            nutils.assess_status('test-config')
            asf.assert_called_once_with('test-config')
            callee.assert_called_once_with()
            self.os_application_version_set.assert_called_with(
                nutils.VERSION_PACKAGE
            )

    @patch.object(nutils, 'get_optional_interfaces')
    @patch.object(nutils, 'REQUIRED_INTERFACES')
    @patch.object(nutils, 'services')
    @patch.object(nutils, 'determine_ports')
    @patch.object(nutils, 'make_assess_status_func')
    def test_assess_status_func(self,
                                make_assess_status_func,
                                determine_ports,
                                services,
                                REQUIRED_INTERFACES,
                                get_optional_interfaces):
        services.return_value = 's1'
        REQUIRED_INTERFACES.copy.return_value = {'int': ['test 1']}
        get_optional_interfaces.return_value = {'opt': ['test 2']}
        determine_ports.return_value = 'p1'
        nutils.assess_status_func('test-config')
        # ports=None whilst port checks are disabled.
        make_assess_status_func.assert_called_once_with(
            'test-config',
            {'int': ['test 1'], 'opt': ['test 2']},
            charm_func=nutils.check_optional_relations,
            services='s1', ports=None)

    def test_pause_unit_helper(self):
        with patch.object(nutils, '_pause_resume_helper') as prh:
            nutils.pause_unit_helper('random-config')
            prh.assert_called_once_with(nutils.pause_unit, 'random-config')
        with patch.object(nutils, '_pause_resume_helper') as prh:
            nutils.resume_unit_helper('random-config')
            prh.assert_called_once_with(nutils.resume_unit, 'random-config')

    @patch.object(nutils, 'services')
    @patch.object(nutils, 'determine_ports')
    def test_pause_resume_helper(self, determine_ports, services):
        f = MagicMock()
        services.return_value = 's1'
        determine_ports.return_value = 'p1'
        with patch.object(nutils, 'assess_status_func') as asf:
            asf.return_value = 'assessor'
            nutils._pause_resume_helper(f, 'some-config')
            asf.assert_called_once_with('some-config')
            # ports=None whilst port checks are disabled.
            f.assert_called_once_with('assessor', services='s1', ports=None)

    @patch.object(nutils, 'subprocess')
    @patch.object(nutils, 'get_db_url')
    def test_fwaas_migrate_v1_to_v2(self,
                                    get_db_url,
                                    subprocess):
        get_db_url.return_value = 'mysql://localhost:80/testdb'
        nutils.fwaas_migrate_v1_to_v2()
        subprocess.check_call.assert_called_with([
            'neutron-fwaas-migrate-v1-to-v2',
            '--neutron-db-connection=mysql://localhost:80/testdb'
        ])

    @patch.object(nutils, 'config')
    @patch.object(nutils, 'context')
    def test_get_db_url(self,
                        mock_context,
                        mock_config):
        mock_db_context = MagicMock()
        mock_db_context.return_value = {
            'database_type': 'pymysql+mysql',
            'database_user': 'testuser',
            'database_host': 'testhost',
            'database_password': 'testpassword',
            'database': 'testdatabase',
        }
        mock_context.SharedDBContext.return_value = mock_db_context
        self.assertEqual(
            nutils.get_db_url(),
            "pymysql+mysql://testuser:testpassword@testhost/testdatabase"
        )

    @patch.object(nutils, 'config')
    @patch.object(nutils, 'context')
    def test_get_db_url_ssl(self,
                            mock_context,
                            mock_config):
        mock_db_context = MagicMock()
        mock_db_context.return_value = {
            'database_type': 'pymysql+mysql',
            'database_user': 'testuser',
            'database_host': 'testhost',
            'database_password': 'testpassword',
            'database': 'testdatabase',
            'database_ssl_ca': 'foo',
            'database_ssl_cert': 'bar',
            'database_ssl_key': 'baz',
        }
        mock_context.SharedDBContext.return_value = mock_db_context
        self.assertEqual(
            nutils.get_db_url(),
            "pymysql+mysql://testuser:testpassword@testhost/testdatabase"
            "?ssl_ca=foo&ssl_cert=bar&ssl_key=baz"
        )
