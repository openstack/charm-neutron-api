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

from collections import OrderedDict
from copy import deepcopy
from functools import partial
import os
import shutil
import subprocess
import uuid
import glob
import yaml
from base64 import b64encode
from charmhelpers.contrib.openstack import context, templating
from charmhelpers.contrib.openstack.neutron import (
    neutron_plugin_attribute,
)

from charmhelpers.contrib.openstack.utils import (
    os_release,
    get_os_codename_install_source,
    configure_installation_source,
    incomplete_relation_data,
    is_unit_paused_set,
    make_assess_status_func,
    pause_unit,
    resume_unit,
    os_application_version_set,
    token_cache_pkgs,
    enable_memcache,
    CompareOpenStackReleases,
    reset_os_release,
)

from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    log,
    DEBUG,
    relation_ids,
    related_units,
    relation_get,
    relation_set,
    local_unit,
)

from charmhelpers.fetch import (
    apt_update,
    apt_install,
    apt_upgrade,
    add_source,
    filter_missing_packages,
    apt_purge,
    apt_autoremove,
)

from charmhelpers.core.host import (
    lsb_release,
    CompareHostReleases,
    service_stop,
    service_start,
    service_restart,
)

from charmhelpers.contrib.hahelpers.cluster import (
    get_hacluster_config,
)

from charmhelpers.contrib.hahelpers.cluster import is_elected_leader

import neutron_api_context

TEMPLATES = 'templates/'

CLUSTER_RES = 'grp_neutron_vips'

# removed from original: charm-helper-sh
BASE_PACKAGES = [
    'apache2',
    'haproxy',
    'python-keystoneclient',
    'python-mysqldb',
    'python-psycopg2',
    'python-six',
    'uuid',
]

KILO_PACKAGES = [
    'python-neutron-lbaas',
    'python-neutron-fwaas',
    'python-neutron-vpnaas',
]

PY3_PACKAGES = [
    'python3-neutron',
    'python3-neutron-lbaas',
    'python3-neutron-fwaas',
    'python3-neutron-dynamic-routing',
    'python3-networking-hyperv',
    'python3-memcache',
]

PURGE_PACKAGES = [
    'python-neutron',
    'python-neutron-lbaas',
    'python-neutron-fwaas',
    'python-neutron-vpnaas',
    'python-neutron-dynamic-routing',
    'python-networking-hyperv',
    'python-memcache',
    'python-keystoneclient',
    'python-mysqldb',
    'python-psycopg2',
]

VERSION_PACKAGE = 'neutron-common'

BASE_SERVICES = [
    'neutron-server'
]
API_PORTS = {
    'neutron-server': 9696,
}

NEUTRON_CONF_DIR = "/etc/neutron"

NEUTRON_CONF = '%s/neutron.conf' % NEUTRON_CONF_DIR
NEUTRON_LBAAS_CONF = '%s/neutron_lbaas.conf' % NEUTRON_CONF_DIR
NEUTRON_VPNAAS_CONF = '%s/neutron_vpnaas.conf' % NEUTRON_CONF_DIR
HAPROXY_CONF = '/etc/haproxy/haproxy.cfg'
APACHE_CONF = '/etc/apache2/sites-available/openstack_https_frontend'
APACHE_24_CONF = '/etc/apache2/sites-available/openstack_https_frontend.conf'
APACHE_SSL_DIR = '/etc/apache2/ssl/neutron'
NEUTRON_DEFAULT = '/etc/default/neutron-server'
CA_CERT_PATH = '/usr/local/share/ca-certificates/keystone_juju_ca_cert.crt'
MEMCACHED_CONF = '/etc/memcached.conf'
API_PASTE_INI = '%s/api-paste.ini' % NEUTRON_CONF_DIR
ADMIN_POLICY = "/etc/neutron/policy.d/00-admin.json"
# NOTE:(fnordahl) placeholder ml2_conf_srov.ini pointing users to ml2_conf.ini
# Due to how neutron init scripts are laid out on various Linux
# distributions we put the [ml2_sriov] section in ml2_conf.ini instead
# of its default ml2_conf_sriov.ini location.
ML2_SRIOV_INI = os.path.join(NEUTRON_CONF_DIR,
                             'plugins/ml2/ml2_conf_sriov.ini')

BASE_RESOURCE_MAP = OrderedDict([
    (NEUTRON_CONF, {
        'services': ['neutron-server'],
        'contexts': [neutron_api_context.NeutronAMQPContext(),
                     context.SharedDBContext(
                         user=config('database-user'),
                         database=config('database'),
                         ssl_dir=NEUTRON_CONF_DIR),
                     neutron_api_context.IdentityServiceContext(
                         service='neutron',
                         service_user='neutron'),
                     context.OSConfigFlagContext(),
                     neutron_api_context.NeutronCCContext(),
                     context.SyslogContext(),
                     context.ZeroMQContext(),
                     context.NotificationDriverContext(),
                     context.BindHostContext(),
                     context.WorkerConfigContext(),
                     context.InternalEndpointContext(),
                     context.MemcacheContext(),
                     neutron_api_context.DesignateContext(),
                     neutron_api_context.NeutronInfobloxContext()],
    }),
    (NEUTRON_DEFAULT, {
        'services': ['neutron-server'],
        'contexts': [neutron_api_context.NeutronCCContext()],
    }),
    (API_PASTE_INI, {
        'services': ['neutron-server'],
        'contexts': [neutron_api_context.NeutronApiApiPasteContext()],
    }),
    (APACHE_CONF, {
        'contexts': [neutron_api_context.ApacheSSLContext()],
        'services': ['apache2'],
    }),
    (APACHE_24_CONF, {
        'contexts': [neutron_api_context.ApacheSSLContext()],
        'services': ['apache2'],
    }),
    (HAPROXY_CONF, {
        'contexts': [context.HAProxyContext(singlenode_mode=True),
                     neutron_api_context.HAProxyContext()],
        'services': ['haproxy'],
    }),
])

# The interface is said to be satisfied if anyone of the interfaces in the
# list has a complete context.
REQUIRED_INTERFACES = {
    'database': ['shared-db'],
    'messaging': ['amqp'],
    'identity': ['identity-service'],
}

LIBERTY_RESOURCE_MAP = OrderedDict([
    (NEUTRON_LBAAS_CONF, {
        'services': ['neutron-server'],
        'contexts': [],
    }),
    (NEUTRON_VPNAAS_CONF, {
        'services': ['neutron-server'],
        'contexts': [],
    }),
])


NEUTRON_DB_INIT_RKEY = 'neutron-db-initialised'
NEUTRON_DB_INIT_ECHO_RKEY = 'neutron-db-initialised-echo'


def is_db_initialised(cluster_rid=None):
    """
    Check whether a db intialisation has been performed by any peer unit.

    We base our decision on whether we or any of our peers has previously
    sent or echoed an initialisation notification.

    @param cluster_rid: current relation id. If none provided, all cluster
                        relation ids will be checked.
    @return: True if there has been a db initialisation otherwise False.
    """
    if cluster_rid:
        rids = [cluster_rid]
    else:
        rids = relation_ids('cluster')

    shared_db_rel_id = (relation_ids('shared-db') or [None])[0]
    if not shared_db_rel_id:
        return False

    for c_rid in rids:
        units = related_units(relid=c_rid) + [local_unit()]
        for unit in units:
            settings = relation_get(unit=unit, rid=c_rid) or {}
            for key in [NEUTRON_DB_INIT_RKEY, NEUTRON_DB_INIT_ECHO_RKEY]:
                if shared_db_rel_id in settings.get(key, ''):
                    return True

    return False


def is_new_dbinit_notification(init_id, echoed_init_id):
    """Returns True if we have a received a new db initialisation notification
    from a peer unit and we have not previously echoed it to indicate that we
    have already performed the necessary actions as result.

    Initialisation notification is expected to be of the format:

    <unit-id-leader-unit>-<shared-db-rel-id>-<uuid>

    @param init_db: received initialisation notification.
    @param echoed_init_db: value currently set for the echo key.
    @return: True if new notification and False if not.
    """
    shared_db_rel_id = (relation_ids('shared-db') or [None])[0]
    return (shared_db_rel_id and init_id and
            (local_unit() not in init_id) and
            (shared_db_rel_id in init_id) and
            (echoed_init_id != init_id))


def check_local_db_actions_complete():
    """Check if we have received db init'd notification and restart services
    if we have not already.

    NOTE: this must only be called from peer relation context.
    """
    if not is_db_initialised():
        return

    settings = relation_get() or {}
    if settings:
        init_id = settings.get(NEUTRON_DB_INIT_RKEY)
        echoed_init_id = relation_get(unit=local_unit(),
                                      attribute=NEUTRON_DB_INIT_ECHO_RKEY)

        # If we have received an init notification from a peer unit
        # (assumed to be the leader) then restart neutron-api and echo the
        # notification and don't restart again unless we receive a new
        # (different) notification.
        if is_new_dbinit_notification(init_id, echoed_init_id):
            if not is_unit_paused_set():
                log("Restarting neutron services following db "
                    "initialisation", level=DEBUG)
                service_restart('neutron-server')

            # Echo notification
            relation_set(**{NEUTRON_DB_INIT_ECHO_RKEY: init_id})


def api_port(service):
    return API_PORTS[service]


def additional_install_locations(plugin, source):
    '''
    Add any required additional package locations for the charm, based
    on the Neutron plugin being used. This will also force an immediate
    package upgrade.
    '''
    release = get_os_codename_install_source(source)
    if plugin == 'Calico':
        if config('calico-origin'):
            calico_source = config('calico-origin')
        elif release in ('icehouse', 'juno', 'kilo'):
            # Prior to the Liberty release, Calico's Nova and Neutron changes
            # were not fully upstreamed, so we need to point to a
            # release-specific PPA that includes Calico-specific Nova and
            # Neutron packages.
            calico_source = 'ppa:project-calico/%s' % release
        else:
            # From Liberty onwards, we can point to a PPA that does not include
            # any patched OpenStack packages, and hence is independent of the
            # OpenStack release.
            calico_source = 'ppa:project-calico/calico-1.4'

        add_source(calico_source)

    elif plugin == 'midonet':
        midonet_origin = config('midonet-origin')
        release_num = midonet_origin.split('-')[1]

        if midonet_origin.startswith('mem'):
            with open(os.path.join(charm_dir(),
                                   'files/midokura.key')) as midokura_gpg_key:
                priv_gpg_key = midokura_gpg_key.read()
            mem_username = config('mem-username')
            mem_password = config('mem-password')
            if release in ('juno', 'kilo', 'liberty'):
                add_source(
                    'deb http://%s:%s@apt.midokura.com/openstack/%s/stable '
                    'trusty main' % (mem_username, mem_password, release),
                    key=priv_gpg_key)
            add_source('http://%s:%s@apt.midokura.com/midonet/v%s/stable '
                       'main' % (mem_username, mem_password, release_num),
                       key=priv_gpg_key)
        else:
            with open(os.path.join(charm_dir(),
                                   'files/midonet.key')) as midonet_gpg_key:
                pub_gpg_key = midonet_gpg_key.read()
            if release in ('juno', 'kilo', 'liberty'):
                add_source(
                    'deb http://repo.midonet.org/openstack-%s stable main' %
                    release, key=pub_gpg_key)

            add_source('deb http://repo.midonet.org/midonet/v%s stable main' %
                       release_num, key=pub_gpg_key)

        apt_update(fatal=True)
        apt_upgrade(fatal=True)


def force_etcd_restart():
    '''
    If etcd has been reconfigured we need to force it to fully restart.
    This is necessary because etcd has some config flags that it ignores
    after the first time it starts, so we need to make it forget them.
    '''
    service_stop('etcd')
    for directory in glob.glob('/var/lib/etcd/*'):
        shutil.rmtree(directory)
    if not is_unit_paused_set():
        service_start('etcd')


def manage_plugin():
    return config('manage-neutron-plugin-legacy-mode')


def determine_packages(source=None):
    # currently all packages match service names
    release = get_os_codename_install_source(source)
    cmp_release = CompareOpenStackReleases(release)
    packages = deepcopy(BASE_PACKAGES)
    if cmp_release >= 'rocky':
        packages.extend(PY3_PACKAGES)
        if cmp_release >= 'train':
            packages.remove('python3-neutron-lbaas')

    for v in resource_map().values():
        packages.extend(v['services'])
        if manage_plugin():
            pkgs = neutron_plugin_attribute(config('neutron-plugin'),
                                            'server_packages',
                                            'neutron')
            packages.extend(pkgs)

    packages.extend(token_cache_pkgs(release=release))

    if cmp_release < 'rocky':
        if cmp_release >= 'kilo':
            packages.extend(KILO_PACKAGES)
        if cmp_release >= 'ocata':
            packages.append('python-neutron-dynamic-routing')
        if cmp_release >= 'pike':
            packages.remove('python-neutron-vpnaas')

        if release == 'kilo' or cmp_release >= 'mitaka':
            packages.append('python-networking-hyperv')

    if config('neutron-plugin') == 'vsp' and cmp_release < 'newton':
        nuage_pkgs = config('nuage-packages').split()
        packages.extend(nuage_pkgs)

    if cmp_release >= 'rocky':
        packages = [p for p in packages if not p.startswith('python-')]

    return list(set(packages))


def determine_purge_packages():
    '''Return a list of packages to purge for the current OS release'''
    cmp_os_source = CompareOpenStackReleases(os_release('neutron-common'))
    if cmp_os_source >= 'rocky':
        return PURGE_PACKAGES
    return []


def remove_old_packages():
    '''Purge any packages that need ot be removed.

    :returns: bool Whether packages were removed.
    '''
    installed_packages = filter_missing_packages(determine_purge_packages())
    if installed_packages:
        apt_purge(installed_packages, fatal=True)
        apt_autoremove(purge=True, fatal=True)
    return bool(installed_packages)


def determine_ports():
    '''Assemble a list of API ports for services we are managing'''
    ports = []
    for services in restart_map().values():
        for service in services:
            try:
                ports.append(API_PORTS[service])
            except KeyError:
                pass
    return list(set(ports))


def resource_map(release=None):
    '''
    Dynamically generate a map of resources that will be managed for a single
    hook execution.
    '''
    release = release or os_release('neutron-common')

    resource_map = deepcopy(BASE_RESOURCE_MAP)
    if CompareOpenStackReleases(release) >= 'liberty':
        resource_map.update(LIBERTY_RESOURCE_MAP)

    if os.path.exists('/etc/apache2/conf-available'):
        resource_map.pop(APACHE_CONF)
    else:
        resource_map.pop(APACHE_24_CONF)

    if manage_plugin():
        # add neutron plugin requirements. nova-c-c only needs the
        # neutron-server associated with configs, not the plugin agent.
        plugin = config('neutron-plugin')
        conf = neutron_plugin_attribute(plugin, 'config', 'neutron')
        ctxts = (neutron_plugin_attribute(plugin, 'contexts', 'neutron') or
                 [])
        services = neutron_plugin_attribute(plugin, 'server_services',
                                            'neutron')
        resource_map[conf] = {}
        resource_map[conf]['services'] = services
        resource_map[conf]['contexts'] = ctxts
        resource_map[conf]['contexts'].append(
            neutron_api_context.NeutronCCContext())

        if ('kilo' <= CompareOpenStackReleases(release) <= 'mitaka' and
                config('enable-sriov')):
            resource_map[ML2_SRIOV_INI] = {}
            resource_map[ML2_SRIOV_INI]['services'] = services
            resource_map[ML2_SRIOV_INI]['contexts'] = []
    else:
        plugin_ctxt_instance = neutron_api_context.NeutronApiSDNContext()
        if (plugin_ctxt_instance.is_default('core_plugin') and
                plugin_ctxt_instance.is_default('neutron_plugin_config')):
            # The default core plugin is ML2.  If the driver provided by plugin
            # subordinate is built on top of ML2, the subordinate will have use
            # for influencing existing template variables as well as injecting
            # sections into the ML2 configuration file.
            conf = neutron_plugin_attribute('ovs', 'config', 'neutron')
            services = neutron_plugin_attribute('ovs', 'server_services',
                                                'neutron')
            if conf not in resource_map:
                resource_map[conf] = {}
                resource_map[conf]['services'] = services
                resource_map[conf]['contexts'] = [
                    neutron_api_context.NeutronCCContext(),
                ]
            resource_map[conf]['contexts'].append(
                neutron_api_context.NeutronApiSDNContext(
                    config_file=conf)
            )

        resource_map[NEUTRON_CONF]['contexts'].append(
            plugin_ctxt_instance,
        )
        resource_map[NEUTRON_DEFAULT]['contexts'] = \
            [neutron_api_context.NeutronApiSDNConfigFileContext()]
    if enable_memcache(release=release):
        resource_map[MEMCACHED_CONF] = {
            'contexts': [context.MemcacheContext()],
            'services': ['memcached']}

    return resource_map


def register_configs(release=None):
    release = release or os_release('neutron-common')
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)
    for cfg, rscs in resource_map().items():
        configs.register(cfg, rscs['contexts'])
    return configs


def restart_map():
    restart_map = OrderedDict([(cfg, v['services'])
                               for cfg, v in resource_map().items()
                               if v['services']])
    if os.path.isdir(APACHE_SSL_DIR):
        restart_map['{}/*'.format(APACHE_SSL_DIR)] = ['apache2',
                                                      'neutron-server']
    return restart_map


def services():
    ''' Returns a list of services associate with this charm '''
    _services = []
    for v in restart_map().values():
        _services = _services + v
    return list(set(_services))


def keystone_ca_cert_b64():
    '''Returns the local Keystone-provided CA cert if it exists, or None.'''
    if not os.path.isfile(CA_CERT_PATH):
        return None
    with open(CA_CERT_PATH) as _in:
        return b64encode(_in.read())


def do_openstack_upgrade(configs):
    """
    Perform an upgrade.  Takes care of upgrading packages, rewriting
    configs, database migrations and potentially any other post-upgrade
    actions.

    :param configs: The charms main OSConfigRenderer object.
    """
    cur_os_rel = os_release('neutron-common')
    new_src = config('openstack-origin')
    new_os_rel = get_os_codename_install_source(new_src)

    log('Performing OpenStack upgrade to %s.' % (new_os_rel))

    configure_installation_source(new_src)
    dpkg_opts = [
        '--option', 'Dpkg::Options::=--force-confnew',
        '--option', 'Dpkg::Options::=--force-confdef',
    ]
    apt_update(fatal=True)
    apt_upgrade(options=dpkg_opts, fatal=True, dist=True)
    reset_os_release()
    pkgs = determine_packages(new_src)
    # Sort packages just to make unit tests easier
    pkgs.sort()
    apt_install(packages=pkgs,
                options=dpkg_opts,
                fatal=True)

    remove_old_packages()

    # set CONFIGS to load templates from new release
    configs.set_release(openstack_release=new_os_rel)
    # write all configurations for any new parts required for
    # the new release.
    configs.write_all()
    # Before kilo it's nova-cloud-controllers job
    if is_elected_leader(CLUSTER_RES):
        # Stamping seems broken and unnecessary in liberty (Bug #1536675)
        if CompareOpenStackReleases(os_release('neutron-common')) < 'liberty':
            stamp_neutron_database(cur_os_rel)
        migrate_neutron_database(upgrade=True)
        if CompareOpenStackReleases(new_os_rel) >= 'stein':
            fwaas_migrate_v1_to_v2()


# TODO: make an attribute of the context for shared usage
def get_db_url():
    '''
    Retrieve the Database URL for the Neutron DB

    :returns: oslo.db formatted connection string for the DB
    :rtype: str
    '''
    ctxt = context.SharedDBContext(
        user=config('database-user'),
        database=config('database'),
        ssl_dir=NEUTRON_CONF_DIR)()
    # NOTE: core database url
    database_url = (
        "{database_type}://"
        "{database_user}:{database_password}@"
        "{database_host}/{database}".format(**ctxt)
    )
    # NOTE: optional SSL configuration
    if ctxt.get('database_ssl_ca'):
        ssl_args = [
            'ssl_ca={}'.format(ctxt['database_ssl_ca'])
        ]
        if ctxt.get('database_ssl_cert'):
            ssl_args.append('ssl_cert={}'.format(ctxt['database_ssl_cert']))
            ssl_args.append('ssl_key={}'.format(ctxt['database_ssl_key']))
        database_url = "{}?{}".format(
            database_url,
            "&".join(ssl_args)
        )
    return database_url


def fwaas_migrate_v1_to_v2():
    '''Migrate any existing v1 firewall definitions to v2'''
    cmd = [
        'neutron-fwaas-migrate-v1-to-v2',
        '--neutron-db-connection={}'.format(get_db_url())
    ]
    subprocess.check_call(cmd)


def stamp_neutron_database(release):
    '''Stamp the database with the current release before upgrade.'''
    log('Stamping the neutron database with release %s.' % release)
    plugin = config('neutron-plugin')
    cmd = ['neutron-db-manage',
           '--config-file', NEUTRON_CONF,
           '--config-file', neutron_plugin_attribute(plugin,
                                                     'config',
                                                     'neutron'),
           'stamp',
           release]
    subprocess.check_output(cmd)


def nuage_vsp_juno_neutron_migration():
    log('Nuage VSP with Juno Relase')
    nuage_migration_db_path = '/usr/lib/python2.7/dist-packages/'\
                              'neutron/db/migration/nuage'
    nuage_migrate_hybrid_file_path = os.path.join(
        nuage_migration_db_path, 'migrate_hybrid_juno.py')
    nuage_config_file = neutron_plugin_attribute(config('neutron-plugin'),
                                                 'config', 'neutron')
    if os.path.exists(nuage_migration_db_path):
        if os.path.exists(nuage_migrate_hybrid_file_path):
            if os.path.exists(nuage_config_file):
                log('Running Migartion Script for Juno Release')
                cmd = 'sudo python ' + nuage_migrate_hybrid_file_path + \
                      ' --config-file ' + nuage_config_file + \
                      ' --config-file ' + NEUTRON_CONF
                log(cmd)
                subprocess.check_output(cmd, shell=True)
            else:
                e = nuage_config_file+' doesnot exist'
                log(e)
                raise Exception(e)
        else:
            e = nuage_migrate_hybrid_file_path+' doesnot exists'
            log(e)
            raise Exception(e)
    else:
        e = nuage_migration_db_path+' doesnot exists'
        log(e)
        raise Exception(e)


def migrate_neutron_database(upgrade=False):
    '''Initializes a new database or upgrades an existing database.'''

    if not upgrade and is_db_initialised():
        log("Database is already initialised.", level=DEBUG)
        return

    log('Migrating the neutron database.')
    if(os_release('neutron-server') == 'juno' and
       config('neutron-plugin') == 'vsp'):
        nuage_vsp_juno_neutron_migration()
    else:
        plugin = config('neutron-plugin')
        cmd = ['neutron-db-manage',
               '--config-file', NEUTRON_CONF,
               '--config-file', neutron_plugin_attribute(plugin,
                                                         'config',
                                                         'neutron'),
               'upgrade',
               'head']
        subprocess.check_output(cmd)

    cluster_rids = relation_ids('cluster')
    if cluster_rids:
        # Notify peers so that services get restarted
        log("Notifying peer(s) that db is initialised and restarting services",
            level=DEBUG)
        for r_id in cluster_rids:
            if not is_unit_paused_set():
                service_restart('neutron-server')

            # Notify peers that tey should also restart their services
            shared_db_rel_id = (relation_ids('shared-db') or [None])[0]
            id = "{}-{}-{}".format(local_unit(), shared_db_rel_id,
                                   uuid.uuid4())
            relation_set(relation_id=r_id, **{NEUTRON_DB_INIT_RKEY: id})


def setup_ipv6():
    ubuntu_rel = lsb_release()['DISTRIB_CODENAME'].lower()
    if CompareHostReleases(ubuntu_rel) < "trusty":
        raise Exception("IPv6 is not supported in the charms for Ubuntu "
                        "versions less than Trusty 14.04")

    # Need haproxy >= 1.5.3 for ipv6 so for Trusty if we are <= Kilo we need to
    # use trusty-backports otherwise we can use the UCA.
    this_os_release = os_release('neutron-server')
    if (ubuntu_rel == 'trusty' and
            CompareOpenStackReleases(this_os_release) < 'liberty'):
        add_source('deb http://archive.ubuntu.com/ubuntu trusty-backports '
                   'main')
        apt_update()
        apt_install('haproxy/trusty-backports', fatal=True)


class FakeNeutronClient(object):
    '''Fake wrapper for Neutron Client'''

    def __init__(self, username, password, tenant_name,
                 auth_url, region_name):
        self.env = {
            'OS_USERNAME': username,
            'OS_PASSWORD': password,
            'OS_TENANT_NAME': tenant_name,
            'OS_AUTH_URL': auth_url,
            'OS_REGION': region_name,
        }

    def list_routers(self):
        cmd = ['neutron', 'router-list', '-f', 'yaml']
        try:
            routers = subprocess.check_output(
                cmd, env=self.env).decode('UTF-8')
            return {'routers': yaml.load(routers)}
        except subprocess.CalledProcessError:
            return {'routers': []}


def get_neutron_client():
    ''' Return a neutron client if possible '''
    env = neutron_api_context.IdentityServiceContext()()
    if not env:
        log('Unable to check resources at this time')
        return None

    auth_url = '{auth_protocol}://{auth_host}:{auth_port}/v2.0'.format(**env)

    return FakeNeutronClient(username=env['admin_user'],
                             password=env['admin_password'],
                             tenant_name=env['admin_tenant_name'],
                             auth_url=auth_url,
                             region_name=env['region'])


def router_feature_present(feature):
    ''' Check For dvr enabled routers '''
    neutron_client = get_neutron_client()
    for router in neutron_client.list_routers()['routers']:
        if router.get(feature, False):
            return True
    return False

l3ha_router_present = partial(router_feature_present, feature='ha')

dvr_router_present = partial(router_feature_present, feature='distributed')


def neutron_ready():
    ''' Check if neutron is ready by running arbitrary query'''
    neutron_client = get_neutron_client()
    if not neutron_client:
        log('No neutron client, neutron not ready')
        return False
    try:
        neutron_client.list_routers()
        log('neutron client ready')
        return True
    except:
        log('neutron query failed, neutron not ready ')
        return False


def get_optional_interfaces():
    """Return the optional interfaces that should be checked if the relavent
    relations have appeared.
    :returns: {general_interface: [specific_int1, specific_int2, ...], ...}
    """
    optional_interfaces = {}
    if relation_ids('ha'):
        optional_interfaces['ha'] = ['cluster']
    return optional_interfaces


def check_optional_relations(configs):
    """Check that if we have a relation_id for high availability that we can
    get the hacluster config.  If we can't then we are blocked.  This function
    is called from assess_status/set_os_workload_status as the charm_func and
    needs to return either "unknown", "" if there is no problem or the status,
    message if there is a problem.

    :param configs: an OSConfigRender() instance.
    :return 2-tuple: (string, string) = (status, message)
    """
    if relation_ids('ha'):
        try:
            get_hacluster_config()
        except:
            return ('blocked',
                    'hacluster missing configuration: '
                    'vip, vip_iface, vip_cidr')
    # return 'unknown' as the lowest priority to not clobber an existing
    # status.
    return 'unknown', ''


def is_api_ready(configs):
    return (not incomplete_relation_data(configs, REQUIRED_INTERFACES))


def assess_status(configs):
    """Assess status of current unit
    Decides what the state of the unit should be based on the current
    configuration.
    SIDE EFFECT: calls set_os_workload_status(...) which sets the workload
    status of the unit.
    Also calls status_set(...) directly if paused state isn't complete.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    assess_status_func(configs)()
    os_application_version_set(VERSION_PACKAGE)


def assess_status_func(configs):
    """Helper function to create the function that will assess_status() for
    the unit.
    Uses charmhelpers.contrib.openstack.utils.make_assess_status_func() to
    create the appropriate status function and then returns it.
    Used directly by assess_status() and also for pausing and resuming
    the unit.

    NOTE: REQUIRED_INTERFACES is augmented with the optional interfaces
    depending on the current config before being passed to the
    make_assess_status_func() function.

    NOTE(ajkavanagh) ports are not checked due to race hazards with services
    that don't behave sychronously w.r.t their service scripts.  e.g.
    apache2.

    @param configs: a templating.OSConfigRenderer() object
    @return f() -> None : a function that assesses the unit's workload status
    """
    required_interfaces = REQUIRED_INTERFACES.copy()
    required_interfaces.update(get_optional_interfaces())
    return make_assess_status_func(
        configs, required_interfaces,
        charm_func=check_optional_relations,
        services=services(), ports=None)


def pause_unit_helper(configs):
    """Helper function to pause a unit, and then call assess_status(...) in
    effect, so that the status is correctly updated.
    Uses charmhelpers.contrib.openstack.utils.pause_unit() to do the work.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    _pause_resume_helper(pause_unit, configs)


def resume_unit_helper(configs):
    """Helper function to resume a unit, and then call assess_status(...) in
    effect, so that the status is correctly updated.
    Uses charmhelpers.contrib.openstack.utils.resume_unit() to do the work.
    @param configs: a templating.OSConfigRenderer() object
    @returns None - this function is executed for its side-effect
    """
    _pause_resume_helper(resume_unit, configs)


def _pause_resume_helper(f, configs):
    """Helper function that uses the make_assess_status_func(...) from
    charmhelpers.contrib.openstack.utils to create an assess_status(...)
    function that can be used with the pause/resume of the unit
    @param f: the function to be used with the assess_status(...) function
    @returns None - this function is executed for its side-effect
    """
    # TODO(ajkavanagh) - ports= has been left off because of the race hazard
    # that exists due to service_start()
    f(assess_status_func(configs),
      services=services(),
      ports=None)
