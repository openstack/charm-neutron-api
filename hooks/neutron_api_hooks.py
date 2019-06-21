#!/usr/bin/env python3
#
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
import uuid
from subprocess import (
    check_call,
)

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    local_unit,
    log,
    DEBUG,
    ERROR,
    relation_get,
    relation_ids,
    relation_set,
    status_set,
    open_port,
    unit_get,
    related_units,
    is_leader,
)

from charmhelpers.core.host import (
    mkdir,
    service_reload,
    service_restart,
)

from charmhelpers.fetch import (
    apt_install,
    add_source,
    apt_update,
    filter_installed_packages,
)

from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    openstack_upgrade_available,
    os_release,
    sync_db_with_multi_ipv6_addresses,
    is_unit_paused_set,
    pausable_restart_on_change as restart_on_change,
    CompareOpenStackReleases,
    series_upgrade_prepare,
    series_upgrade_complete,
)

from neutron_api_utils import (
    additional_install_locations,
    API_PASTE_INI,
    api_port,
    assess_status,
    CLUSTER_RES,
    determine_packages,
    determine_ports,
    do_openstack_upgrade,
    dvr_router_present,
    force_etcd_restart,
    is_api_ready,
    l3ha_router_present,
    migrate_neutron_database,
    NEUTRON_CONF,
    neutron_ready,
    register_configs,
    restart_map,
    services,
    setup_ipv6,
    check_local_db_actions_complete,
    pause_unit_helper,
    resume_unit_helper,
    remove_old_packages,
    is_db_initialised,
)
from neutron_api_context import (
    get_dns_domain,
    get_dvr,
    get_l3ha,
    get_l2population,
    get_overlay_network_type,
    IdentityServiceContext,
    is_qos_requested_and_valid,
    is_vlan_trunking_requested_and_valid,
    is_nfg_logging_enabled,
    is_nsg_logging_enabled,
    EtcdContext,
)

from charmhelpers.contrib.hahelpers.cluster import (
    is_clustered,
    is_elected_leader,
)

from charmhelpers.contrib.openstack.ha.utils import (
    generate_ha_relation_data,
)

from charmhelpers.payload.execd import execd_preinstall

from charmhelpers.contrib.openstack.ip import (
    canonical_url,
    PUBLIC, INTERNAL, ADMIN
)

from charmhelpers.contrib.openstack.neutron import (
    neutron_plugin_attribute,
)

from charmhelpers.contrib.network.ip import (
    get_relation_ip,
)

from charmhelpers.contrib.openstack.cert_utils import (
    get_certificate_request,
    process_certificates,
)

from charmhelpers.contrib.openstack.context import ADDRESS_TYPES

from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.hardening.harden import harden

hooks = Hooks()
CONFIGS = register_configs()


def conditional_neutron_migration():
    """Initialise neutron database if not already done so.

    Runs neutron-manage to initialize a new database or migrate existing and
    restarts services to ensure that the changes are picked up. The first
    (leader) unit to perform this action should have broadcast this information
    to its peers so first we check whether this has already occurred.
    """
    if CompareOpenStackReleases(os_release('neutron-server')) <= 'icehouse':
        log('Not running neutron database migration as migrations are handled '
            'by the neutron-server process.')
        return

    if not is_elected_leader(CLUSTER_RES):
        log('Not running neutron database migration, not leader')
        return

    allowed_units = relation_get('allowed_units')
    if not (allowed_units and local_unit() in allowed_units.split()):
        log('Not running neutron database migration, either no '
            'allowed_units or this unit is not present')
        return

    migrate_neutron_database()


def configure_https():
    '''
    Enables SSL API Apache config if appropriate and kicks identity-service
    with any required api updates.
    '''
    # need to write all to ensure changes to the entire request pipeline
    # propagate (c-api, haprxy, apache)
    CONFIGS.write_all()
    if 'https' in CONFIGS.complete_contexts():
        cmd = ['a2ensite', 'openstack_https_frontend']
        check_call(cmd)
    else:
        cmd = ['a2dissite', 'openstack_https_frontend']
        check_call(cmd)

    # TODO: improve this by checking if local CN certs are available
    # first then checking reload status (see LP #1433114).
    if not is_unit_paused_set():
        service_reload('apache2', restart_on_failure=True)

    for rid in relation_ids('identity-service'):
        identity_joined(rid=rid)


@hooks.hook('install')
@harden()
def install():
    status_set('maintenance', 'Executing pre-install')
    execd_preinstall()
    openstack_origin = config('openstack-origin')
    configure_installation_source(openstack_origin)
    neutron_plugin = config('neutron-plugin')
    additional_install_locations(neutron_plugin, openstack_origin)

    add_source(config('extra-source'), config('extra-key'))
    status_set('maintenance', 'Installing apt packages')
    apt_update(fatal=True)
    packages = determine_packages(openstack_origin)
    apt_install(packages, fatal=True)

    [open_port(port) for port in determine_ports()]

    if neutron_plugin == 'midonet':
        mkdir('/etc/neutron/plugins/midonet', owner='neutron', group='neutron',
              perms=0o755, force=False)


@hooks.hook('vsd-rest-api-relation-joined')
@restart_on_change(restart_map(), stopstart=True)
def relation_set_nuage_cms_name(rid=None):
    if CompareOpenStackReleases(os_release('neutron-server')) >= 'kilo':
        if config('vsd-cms-name') is None:
            e = "Neutron Api hook failed as vsd-cms-name" \
                " is not specified"
            status_set('blocked', e)
        else:
            relation_data = {
                'vsd-cms-name': '{}'.format(config('vsd-cms-name'))
            }
            relation_set(relation_id=rid, **relation_data)


@hooks.hook('vsd-rest-api-relation-changed')
@restart_on_change(restart_map(), stopstart=True)
def vsd_changed(relation_id=None, remote_unit=None):
    if config('neutron-plugin') == 'vsp':
        vsd_ip_address = relation_get('vsd-ip-address')
        if not vsd_ip_address:
            return
        vsd_address = '{}:8443'.format(vsd_ip_address)
        if CompareOpenStackReleases(os_release('neutron-server')) >= 'kilo':
            vsd_cms_id = relation_get('nuage-cms-id')
            log("nuage-vsd-api-relation-changed : cms_id:{}"
                .format(vsd_cms_id))
        nuage_config_file = neutron_plugin_attribute(config('neutron-plugin'),
                                                     'config', 'neutron')
        log('vsd-rest-api-relation-changed: ip address:{}'.format(vsd_address))
        log('vsd-rest-api-relation-changed:{}'.format(nuage_config_file))

        CONFIGS.write(nuage_config_file)


@hooks.hook('upgrade-charm')
@hooks.hook('config-changed')
@restart_on_change(restart_map(), stopstart=True)
@harden()
def config_changed():
    # if we are paused, delay doing any config changed hooks.
    # It is forced on the resume.
    if is_unit_paused_set():
        log("Unit is pause or upgrading. Skipping config_changed", "WARN")
        return

    # If neutron is ready to be queried then check for incompatability between
    # existing neutron objects and charm settings
    if neutron_ready():
        if l3ha_router_present() and not get_l3ha():
            e = ('Cannot disable Router HA while ha enabled routers exist.'
                 ' Please remove any ha routers')
            status_set('blocked', e)
            raise Exception(e)
        if dvr_router_present() and not get_dvr():
            e = ('Cannot disable dvr while dvr enabled routers exist. Please'
                 ' remove any distributed routers')
            log(e, level=ERROR)
            status_set('blocked', e)
            raise Exception(e)
    if config('prefer-ipv6'):
        status_set('maintenance', 'configuring ipv6')
        setup_ipv6()
        sync_db_with_multi_ipv6_addresses(config('database'),
                                          config('database-user'))

    global CONFIGS
    if not config('action-managed-upgrade'):
        if openstack_upgrade_available('neutron-common'):
            status_set('maintenance', 'Running openstack upgrade')
            do_openstack_upgrade(CONFIGS)

    additional_install_locations(
        config('neutron-plugin'),
        config('openstack-origin')
    )
    status_set('maintenance', 'Installing apt packages')
    apt_install(filter_installed_packages(
                determine_packages(config('openstack-origin'))),
                fatal=True)
    packages_removed = remove_old_packages()
    configure_https()
    update_nrpe_config()
    infoblox_changed()
    CONFIGS.write_all()
    if packages_removed and not is_unit_paused_set():
        log("Package purge detected, restarting services", "INFO")
        for s in services():
            service_restart(s)
    for r_id in relation_ids('neutron-api'):
        neutron_api_relation_joined(rid=r_id)
    for r_id in relation_ids('neutron-plugin-api'):
        neutron_plugin_api_relation_joined(rid=r_id)
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)
    for r_id in relation_ids('identity-service'):
        identity_joined(rid=r_id)
    for r_id in relation_ids('ha'):
        ha_joined(relation_id=r_id)
    [cluster_joined(rid) for rid in relation_ids('cluster')]


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'), vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@hooks.hook('amqp-relation-departed')
@restart_on_change(restart_map())
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NEUTRON_CONF)

    for r_id in relation_ids('neutron-plugin-api-subordinate'):
        neutron_plugin_api_subordinate_relation_joined(relid=r_id)


@hooks.hook('shared-db-relation-joined')
def db_joined():
    if config('prefer-ipv6'):
        sync_db_with_multi_ipv6_addresses(config('database'),
                                          config('database-user'))
    else:
        # Avoid churn check for access-network early
        access_network = None
        for unit in related_units():
            access_network = relation_get(unit=unit,
                                          attribute='access-network')
            if access_network:
                break
        host = get_relation_ip('shared-db', cidr_network=access_network)

        relation_set(database=config('database'),
                     username=config('database-user'),
                     hostname=host)


@hooks.hook('shared-db-relation-changed')
@restart_on_change(restart_map())
def db_changed():
    if 'shared-db' not in CONFIGS.complete_contexts():
        log('shared-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write_all()
    conditional_neutron_migration()
    infoblox_changed()
    for r_id in relation_ids('neutron-plugin-api-subordinate'):
        neutron_plugin_api_subordinate_relation_joined(relid=r_id)


@hooks.hook('amqp-relation-broken',
            'identity-service-relation-broken',
            'shared-db-relation-broken')
def relation_broken():
    CONFIGS.write_all()


@hooks.hook('identity-service-relation-joined')
def identity_joined(rid=None, relation_trigger=False):
    if config('vip') and not is_clustered():
        log('Defering registration until clustered', level=DEBUG)
        return

    public_url = '{}:{}'.format(canonical_url(CONFIGS, PUBLIC),
                                api_port('neutron-server'))
    admin_url = '{}:{}'.format(canonical_url(CONFIGS, ADMIN),
                               api_port('neutron-server'))
    internal_url = '{}:{}'.format(canonical_url(CONFIGS, INTERNAL),
                                  api_port('neutron-server')
                                  )
    rel_settings = {
        'neutron_service': 'neutron',
        'neutron_region': config('region'),
        'neutron_public_url': public_url,
        'neutron_admin_url': admin_url,
        'neutron_internal_url': internal_url,
        'quantum_service': None,
        'quantum_region': None,
        'quantum_public_url': None,
        'quantum_admin_url': None,
        'quantum_internal_url': None,
    }
    if relation_trigger:
        rel_settings['relation_trigger'] = str(uuid.uuid4())
    relation_set(relation_id=rid, relation_settings=rel_settings)


@hooks.hook('identity-service-relation-changed')
@restart_on_change(restart_map())
def identity_changed():
    if 'identity-service' not in CONFIGS.complete_contexts():
        log('identity-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NEUTRON_CONF)
    for r_id in relation_ids('neutron-api'):
        neutron_api_relation_joined(rid=r_id)
    for r_id in relation_ids('neutron-plugin-api'):
        neutron_plugin_api_relation_joined(rid=r_id)
    for r_id in relation_ids('neutron-plugin-api-subordinate'):
        neutron_plugin_api_subordinate_relation_joined(relid=r_id)
    configure_https()
    infoblox_changed()


@hooks.hook('neutron-api-relation-joined')
def neutron_api_relation_joined(rid=None):
    base_url = canonical_url(CONFIGS, INTERNAL)
    neutron_url = '%s:%s' % (base_url, api_port('neutron-server'))
    relation_data = {
        'enable-sriov': config('enable-sriov'),
        'neutron-url': neutron_url,
        'neutron-plugin': config('neutron-plugin'),
    }
    if config('neutron-security-groups'):
        relation_data['neutron-security-groups'] = "yes"
    else:
        relation_data['neutron-security-groups'] = "no"

    if is_api_ready(CONFIGS):
        relation_data['neutron-api-ready'] = "yes"
    else:
        relation_data['neutron-api-ready'] = "no"

    # LP Bug#1805645
    dns_domain = get_dns_domain()
    if dns_domain:
        relation_data['dns-domain'] = dns_domain

    relation_set(relation_id=rid, **relation_data)
    # Nova-cc may have grabbed the neutron endpoint so kick identity-service
    # relation to register that its here
    for r_id in relation_ids('identity-service'):
        identity_joined(rid=r_id, relation_trigger=True)


@hooks.hook('neutron-api-relation-changed')
@restart_on_change(restart_map())
def neutron_api_relation_changed():
    CONFIGS.write(NEUTRON_CONF)


@hooks.hook('neutron-load-balancer-relation-joined')
def neutron_load_balancer_relation_joined(rid=None):
    relation_data = {}
    relation_data['neutron-api-ready'] = is_api_ready(CONFIGS)
    relation_set(relation_id=rid, **relation_data)


@hooks.hook('neutron-load-balancer-relation-changed')
@restart_on_change(restart_map())
def neutron_load_balancer_relation_changed(rid=None):
    neutron_load_balancer_relation_joined(rid)
    CONFIGS.write(NEUTRON_CONF)


@hooks.hook('neutron-plugin-api-relation-joined')
def neutron_plugin_api_relation_joined(rid=None):
    if config('neutron-plugin') == 'nsx':
        relation_data = {
            'nsx-username': config('nsx-username'),
            'nsx-password': config('nsx-password'),
            'nsx-cluster-name': config('nsx-cluster-name'),
            'nsx-tz-uuid': config('nsx-tz-uuid'),
            'nsx-l3-uuid': config('nsx-l3-uuid'),
            'nsx-controllers': config('nsx-controllers'),
        }
    else:
        relation_data = {
            'neutron-security-groups': config('neutron-security-groups'),
            'l2-population': get_l2population(),
            'enable-dvr': get_dvr(),
            'enable-l3ha': get_l3ha(),
            'enable-qos': is_qos_requested_and_valid(),
            'enable-vlan-trunking': is_vlan_trunking_requested_and_valid(),
            'enable-nsg-logging': is_nsg_logging_enabled(),
            'enable-nfg-logging': is_nfg_logging_enabled(),
            'overlay-network-type': get_overlay_network_type(),
            'addr': unit_get('private-address'),
            'polling-interval': config('polling-interval'),
            'rpc-response-timeout': config('rpc-response-timeout'),
            'report-interval': config('report-interval'),
            'global-physnet-mtu': config('global-physnet-mtu'),
            'physical-network-mtus': config('physical-network-mtus'),
        }

        # Provide this value to relations since it needs to be set in multiple
        # places e.g. neutron.conf, nova.conf
        net_dev_mtu = config('network-device-mtu')
        if net_dev_mtu:
            relation_data['network-device-mtu'] = net_dev_mtu

    identity_ctxt = IdentityServiceContext()()
    if not identity_ctxt:
        identity_ctxt = {}

    relation_data.update({
        'auth_host': identity_ctxt.get('auth_host'),
        'auth_port': identity_ctxt.get('auth_port'),
        'auth_protocol': identity_ctxt.get('auth_protocol'),
        'service_protocol': identity_ctxt.get('service_protocol'),
        'service_host': identity_ctxt.get('service_host'),
        'service_port': identity_ctxt.get('service_port'),
        'service_tenant': identity_ctxt.get('admin_tenant_name'),
        'service_username': identity_ctxt.get('admin_user'),
        'service_password': identity_ctxt.get('admin_password'),
        'region': config('region'),
    })

    dns_domain = get_dns_domain()
    if dns_domain:
        relation_data['dns-domain'] = dns_domain

    if is_api_ready(CONFIGS):
        relation_data['neutron-api-ready'] = "yes"
    else:
        relation_data['neutron-api-ready'] = "no"

    relation_set(relation_id=rid, **relation_data)


@hooks.hook('cluster-relation-joined')
def cluster_joined(relation_id=None):
    settings = {}

    for addr_type in ADDRESS_TYPES:
        address = get_relation_ip(
            addr_type,
            cidr_network=config('os-{}-network'.format(addr_type)))
        if address:
            settings['{}-address'.format(addr_type)] = address

    settings['private-address'] = get_relation_ip('cluster')

    relation_set(relation_id=relation_id, relation_settings=settings)

    if not relation_id:
        check_local_db_actions_complete()


@hooks.hook('cluster-relation-changed',
            'cluster-relation-departed')
@restart_on_change(restart_map(), stopstart=True)
def cluster_changed():
    CONFIGS.write_all()
    check_local_db_actions_complete()


@hooks.hook('ha-relation-joined')
def ha_joined(relation_id=None):
    extra_settings = {
        'delete_resources': ['cl_nova_haproxy']
    }
    settings = generate_ha_relation_data(
        'neutron',
        extra_settings=extra_settings)
    relation_set(relation_id=relation_id, **settings)


@hooks.hook('ha-relation-changed')
def ha_changed():
    clustered = relation_get('clustered')
    if not clustered or clustered in [None, 'None', '']:
        log('ha_changed: hacluster subordinate'
            ' not fully clustered: %s' % clustered)
        return
    log('Cluster configured, notifying other services and updating '
        'keystone endpoint configuration')
    for rid in relation_ids('identity-service'):
        identity_joined(rid=rid)
    for rid in relation_ids('neutron-api'):
        neutron_api_relation_joined(rid=rid)


@hooks.hook('neutron-plugin-api-subordinate-relation-joined',
            'neutron-plugin-api-subordinate-relation-changed')
@restart_on_change(restart_map(), stopstart=True)
def neutron_plugin_api_subordinate_relation_joined(relid=None):
    '''
    -changed handles relation data set by a subordinate.
    '''
    relation_data = {'neutron-api-ready': 'no'}
    if is_api_ready(CONFIGS):
        relation_data['neutron-api-ready'] = "yes"
    relation_set(relation_id=relid, **relation_data)

    # there is no race condition with the neutron service restart
    # as juju propagates the changes done in relation_set only after
    # the hook exists
    CONFIGS.write(API_PASTE_INI)


@hooks.hook('neutron-plugin-api-subordinate-relation-changed')
@restart_on_change(restart_map(), stopstart=True)
def neutron_plugin_api_relation_changed():
    CONFIGS.write_all()


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    apt_install('python-dbus')
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)
    nrpe.copy_nrpe_checks()
    nrpe.add_init_service_checks(nrpe_setup, services(), current_unit)

    nrpe.add_haproxy_checks(nrpe_setup, current_unit)
    nrpe_setup.write()


@hooks.hook('etcd-proxy-relation-joined')
@hooks.hook('etcd-proxy-relation-changed')
def etcd_proxy_force_restart(relation_id=None):
    # note(cory.benfield): Mostly etcd does not require active management,
    # but occasionally it does require a full config nuking. This does not
    # play well with the standard neutron-api config management, so we
    # treat etcd like the special snowflake it insists on being.
    CONFIGS.register('/etc/init/etcd.conf', [EtcdContext()])
    CONFIGS.write('/etc/init/etcd.conf')
    CONFIGS.register('/etc/default/etcd', [EtcdContext()])
    CONFIGS.write('/etc/default/etcd')

    if 'etcd-proxy' in CONFIGS.complete_contexts():
        force_etcd_restart()


@hooks.hook('midonet-relation-joined')
@hooks.hook('midonet-relation-changed')
@hooks.hook('midonet-relation-departed')
@restart_on_change(restart_map())
def midonet_changed():
    CONFIGS.write_all()


@hooks.hook('external-dns-relation-joined',
            'external-dns-relation-changed',
            'external-dns-relation-departed',
            'external-dns-relation-broken')
@restart_on_change(restart_map())
def designate_changed():
    CONFIGS.write_all()


@hooks.hook('infoblox-neutron-relation-changed')
@restart_on_change(restart_map)
def infoblox_changed():
    # The neutron DB upgrade will add new tables to
    # neutron db related to infoblox service.
    # Please take a look to charm-infoblox docs.
    if 'infoblox-neutron' not in CONFIGS.complete_contexts():
        log('infoblox-neutron relation incomplete. Peer not ready?')
        return

    CONFIGS.write(NEUTRON_CONF)

    if is_leader():
        ready = False
        if is_db_initialised() and neutron_ready():
            migrate_neutron_database(upgrade=True)
            ready = True
        for rid in relation_ids('infoblox-neutron'):
            relation_set(relation_id=rid, neutron_api_ready=ready)


@hooks.hook('infoblox-neutron-relation-departed',
            'infoblox-neutron-relation-broken')
@restart_on_change(restart_map)
def infoblox_departed():
    CONFIGS.write_all()


@hooks.hook('update-status')
@harden()
@harden()
def update_status():
    log('Updating status.')


@hooks.hook('certificates-relation-joined')
def certs_joined(relation_id=None):
    relation_set(
        relation_id=relation_id,
        relation_settings=get_certificate_request())


@hooks.hook('certificates-relation-changed')
@restart_on_change(restart_map(), stopstart=True)
def certs_changed(relation_id=None, unit=None):
    process_certificates('neutron', relation_id, unit)
    configure_https()


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    log("Running prepare series upgrade hook", "INFO")
    series_upgrade_prepare(
        pause_unit_helper, CONFIGS)


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    log("Running complete series upgrade hook", "INFO")
    series_upgrade_complete(
        resume_unit_helper, CONFIGS)


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status(CONFIGS)


if __name__ == '__main__':
    main()
