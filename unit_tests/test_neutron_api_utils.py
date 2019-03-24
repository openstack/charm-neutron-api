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
    'add_source',
    'b64encode',
    'config',
    'configure_installation_source',
    'get_os_codename_install_source',
    'git_pip_venv_dir',
    'git_src_dir',
    'log',
    'lsb_release',
    'neutron_plugin_attribute',
    'os_release',
    'pip_install',
    'render',
    'service_restart',
    'subprocess',
    'is_elected_leader',
    'service_stop',
    'service_start',
    'glob',
    'os_application_version_set',
]

openstack_origin_git = \
    """repositories:
         - {name: requirements,
            repository: 'https://git.openstack.org/openstack/requirements',
            branch: stable/juno}
         - {name: neutron,
            repository: 'https://git.openstack.org/openstack/neutron',
            branch: stable/juno}"""


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

    @patch.object(nutils, 'git_install_requested')
    def test_determine_packages(self, git_requested):
        git_requested.return_value = False
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-ml2'])
        self.assertItemsEqual(pkg_list, expect)

    @patch.object(nutils, 'git_install_requested')
    def test_determine_vsp_packages(self, git_requested):
        git_requested.return_value = False
        self.test_config.set('nuage-packages',
                             'python-nuagenetlib nuage-neutron')
        self.test_config.set('neutron-plugin', 'vsp')
        self.get_os_codename_install_source.return_value = 'juno'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-nuage',
                       'python-nuagenetlib', 'nuage-neutron'])
        self.assertItemsEqual(pkg_list, expect)

    @patch.object(nutils, 'git_install_requested')
    def test_determine_packages_kilo(self, git_requested):
        git_requested.return_value = False
        self.get_os_codename_install_source.return_value = 'kilo'
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server', 'neutron-plugin-ml2',
                      'python-networking-hyperv'])
        expect.extend(nutils.KILO_PACKAGES)
        self.assertItemsEqual(pkg_list, expect)

    @patch.object(nutils, 'git_install_requested')
    def test_determine_packages_noplugin(self, git_requested):
        git_requested.return_value = False
        self.test_config.set('manage-neutron-plugin-legacy-mode', False)
        pkg_list = nutils.determine_packages()
        expect = deepcopy(nutils.BASE_PACKAGES)
        expect.extend(['neutron-server'])
        self.assertItemsEqual(pkg_list, expect)

    def test_determine_ports(self):
        port_list = nutils.determine_ports()
        self.assertItemsEqual(port_list, [9696])

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map(self, _path_exists, _manage_plugin):
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
    def test_resource_map_apache24(self, _path_exists, _manage_plugin):
        _path_exists.return_value = True
        _manage_plugin.return_value = True
        _map = nutils.resource_map()
        confs = [nutils.NEUTRON_CONF, nutils.NEUTRON_DEFAULT,
                 nutils.APACHE_24_CONF]
        [self.assertIn(q_conf, _map.keys()) for q_conf in confs]
        self.assertTrue(nutils.APACHE_CONF not in _map.keys())

    @patch.object(nutils, 'manage_plugin')
    @patch('os.path.exists')
    def test_resource_map_noplugin(self, _path_exists, _manage_plugin):
        _path_exists.return_value = True
        _manage_plugin.return_value = False
        _map = nutils.resource_map()
        found_sdn_ctxt = False
        found_sdnconfig_ctxt = False
        for ctxt in _map[nutils.NEUTRON_CONF]['contexts']:
            if isinstance(ctxt, ncontext.NeutronApiSDNContext):
                found_sdn_ctxt = True
        for ctxt in _map[nutils.NEUTRON_DEFAULT]['contexts']:
            if isinstance(ctxt, ncontext.NeutronApiSDNConfigFileContext):
                found_sdnconfig_ctxt = True
        self.assertTrue(found_sdn_ctxt and found_sdnconfig_ctxt)

    @patch('os.path.exists')
    def test_restart_map(self, mock_path_exists):
        mock_path_exists.return_value = False
        _restart_map = nutils.restart_map()
        ML2CONF = "/etc/neutron/plugins/ml2/ml2_conf.ini"
        expect = OrderedDict([
            (nutils.NEUTRON_CONF, {
                'services': ['neutron-server'],
            }),
            (nutils.NEUTRON_DEFAULT, {
                'services': ['neutron-server'],
            }),
            (ML2CONF, {
                'services': ['neutron-server'],
            }),
            (nutils.APACHE_CONF, {
                'services': ['apache2'],
            }),
            (nutils.HAPROXY_CONF, {
                'services': ['haproxy'],
            }),
        ])
        self.assertItemsEqual(_restart_map, expect)

    @patch('os.path.exists')
    def test_register_configs(self, mock_path_exists):
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
                 '/etc/default/neutron-server',
                 '/etc/neutron/plugins/ml2/ml2_conf.ini',
                 '/etc/apache2/sites-available/openstack_https_frontend',
                 '/etc/haproxy/haproxy.cfg']
        self.assertItemsEqual(_regconfs.configs, confs)

    @patch('os.path.isfile')
    def test_keystone_ca_cert_b64_no_cert_file(self, _isfile):
        _isfile.return_value = False
        cert = nutils.keystone_ca_cert_b64()
        self.assertEquals(cert, None)

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
    @patch.object(nutils, 'git_install_requested')
    def test_do_openstack_upgrade(self, git_requested,
                                  stamp_neutron_db, migrate_neutron_db,
                                  gsrc):
        git_requested.return_value = False
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
        migrate_neutron_db.assert_called_with()

    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    @patch.object(nutils, 'git_install_requested')
    def test_do_openstack_upgrade_liberty(self, git_requested,
                                          stamp_neutron_db, migrate_neutron_db,
                                          gsrc):
        git_requested.return_value = False
        self.is_elected_leader.return_value = True
        self.os_release.return_value = 'liberty'
        self.config.side_effect = self.test_config.get
        self.test_config.set('openstack-origin', 'cloud:trusty-mitaka')
        gsrc.return_value = 'mitaka'
        self.get_os_codename_install_source.return_value = 'mitaka'
        configs = MagicMock()
        nutils.do_openstack_upgrade(configs)
        self.assertFalse(stamp_neutron_db.called)

    @patch.object(charmhelpers.contrib.openstack.utils,
                  'get_os_codename_install_source')
    @patch.object(nutils, 'migrate_neutron_database')
    @patch.object(nutils, 'stamp_neutron_database')
    @patch.object(nutils, 'git_install_requested')
    def test_do_openstack_upgrade_notleader(self, git_requested,
                                            stamp_neutron_db,
                                            migrate_neutron_db,
                                            gsrc):
        git_requested.return_value = False
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
    @patch('neutronclient.v2_0.client.Client')
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
        self.assertEquals(nutils.get_neutron_client(), None)

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
        self.assertEquals(nutils.router_feature_present('ha'), False)

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
        self.assertEquals(nutils.router_feature_present('ha'), False)

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
        self.assertEquals(nutils.router_feature_present('ha'), True)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready(self, get_neutron_client):
        dummy_client = MagicMock()
        dummy_client.list_routers.return_value = []
        get_neutron_client.return_value = dummy_client
        self.assertEquals(nutils.neutron_ready(), True)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready_noclient(self, get_neutron_client):
        get_neutron_client.return_value = None
        self.assertEquals(nutils.neutron_ready(), False)

    @patch.object(nutils, 'get_neutron_client')
    def test_neutron_ready_clientexception(self, get_neutron_client):
        dummy_client = MagicMock()
        dummy_client.list_routers.side_effect = Exception('Boom!')
        get_neutron_client.return_value = dummy_client
        self.assertEquals(nutils.neutron_ready(), False)

    @patch.object(nutils, 'git_install_requested')
    @patch.object(nutils, 'git_clone_and_install')
    @patch.object(nutils, 'git_post_install')
    @patch.object(nutils, 'git_pre_install')
    def test_git_install(self, git_pre, git_post, git_clone_and_install,
                         git_requested):
        projects_yaml = openstack_origin_git
        git_requested.return_value = True
        nutils.git_install(projects_yaml)
        self.assertTrue(git_pre.called)
        git_clone_and_install.assert_called_with(openstack_origin_git,
                                                 core_project='neutron')
        self.assertTrue(git_post.called)

    @patch.object(nutils, 'mkdir')
    @patch.object(nutils, 'write_file')
    @patch.object(nutils, 'add_user_to_group')
    @patch.object(nutils, 'add_group')
    @patch.object(nutils, 'adduser')
    def test_git_pre_install(self, adduser, add_group, add_user_to_group,
                             write_file, mkdir):
        nutils.git_pre_install()
        adduser.assert_called_with('neutron', shell='/bin/bash',
                                   system_user=True)
        add_group.assert_called_with('neutron', system_group=True)
        add_user_to_group.assert_called_with('neutron', 'neutron')
        expected = [
            call('/var/lib/neutron', owner='neutron',
                 group='neutron', perms=0755, force=False),
            call('/var/lib/neutron/lock', owner='neutron',
                 group='neutron', perms=0755, force=False),
            call('/var/log/neutron', owner='neutron',
                 group='neutron', perms=0755, force=False),
        ]
        self.assertEquals(mkdir.call_args_list, expected)
        expected = [
            call('/var/log/neutron/server.log', '', owner='neutron',
                 group='neutron', perms=0600),
        ]
        self.assertEquals(write_file.call_args_list, expected)

    @patch('os.path.join')
    @patch('os.path.exists')
    @patch('os.symlink')
    @patch('shutil.copytree')
    @patch('shutil.rmtree')
    @patch('subprocess.check_call')
    def test_git_post_install_upstart(self, check_call, rmtree, copytree,
                                      symlink, exists, join):
        projects_yaml = openstack_origin_git
        join.return_value = 'joined-string'
        self.git_pip_venv_dir.return_value = '/mnt/openstack-git/venv'
        self.lsb_release.return_value = {'DISTRIB_RELEASE': '15.04'}
        nutils.git_post_install(projects_yaml)
        expected = [
            call('joined-string', '/etc/neutron'),
            call('joined-string', '/etc/neutron/plugins'),
            call('joined-string', '/etc/neutron/rootwrap.d'),
        ]
        copytree.assert_has_calls(expected)
        expected = [
            call('joined-string', '/usr/local/bin/neutron-rootwrap'),
            call('joined-string', '/usr/local/bin/neutron-db-manage'),
        ]
        symlink.assert_has_calls(expected, any_order=True)
        neutron_api_context = {
            'service_description': 'Neutron API server',
            'charm_name': 'neutron-api',
            'process_name': 'neutron-server',
            'executable_name': 'joined-string',
        }
        expected = [
            call('git/neutron_sudoers', '/etc/sudoers.d/neutron_sudoers', {},
                 perms=0o440),
            call('git/upstart/neutron-server.upstart',
                 '/etc/init/neutron-server.conf',
                 neutron_api_context, perms=0o644),
        ]
        self.assertEquals(self.render.call_args_list, expected)
        expected = [
            call('neutron-server'),
        ]
        self.assertEquals(self.service_restart.call_args_list, expected)

    @patch('os.listdir')
    @patch('os.path.join')
    @patch('os.path.exists')
    @patch('os.symlink')
    @patch('shutil.copytree')
    @patch('shutil.rmtree')
    @patch('subprocess.check_call')
    def test_git_post_install_systemd(self, check_call, rmtree, copytree,
                                      symlink, exists, join, listdir):
        projects_yaml = openstack_origin_git
        join.return_value = 'joined-string'
        self.git_pip_venv_dir.return_value = '/mnt/openstack-git/venv'
        self.lsb_release.return_value = {'DISTRIB_RELEASE': '15.10'}
        nutils.git_post_install(projects_yaml)
        expected = [
            call('git/neutron_sudoers', '/etc/sudoers.d/neutron_sudoers',
                 {}, perms=288),
            call('git/neutron-server.init.in.template', 'joined-string',
                 {'daemon_path': 'joined-string'}, perms=420)
        ]
        self.assertEquals(self.render.call_args_list, expected)

    def test_stamp_neutron_database(self):
        nutils.stamp_neutron_database('icehouse')
        cmd = ['neutron-db-manage',
               '--config-file', '/etc/neutron/neutron.conf',
               '--config-file', '/etc/neutron/plugins/ml2/ml2_conf.ini',
               'stamp',
               'icehouse']
        self.subprocess.check_output.assert_called_with(cmd)

    def test_migrate_neutron_database(self):
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
