# Overview

This principle charm provides the OpenStack Neutron API service which was
previously provided by the nova-cloud-controller charm.

When this charm is related to the nova-cloud-controller charm the nova-cloud
controller charm will shutdown its api service, de-register it from keystone
and inform the compute nodes of the new neutron url.

# Usage

To deploy (partial deployment only):

    juju deploy neutron-api
    juju deploy neutron-openvswitch

    juju add-relation neutron-api mysql
    juju add-relation neutron-api rabbitmq-server
    juju add-relation neutron-api neutron-openvswitch
    juju add-relation neutron-api nova-cloud-controller

This charm also supports scale out and high availability using the hacluster
charm:

    juju deploy hacluster neutron-hacluster
    juju add-unit neutron-api
    juju set neutron-api vip=<VIP FOR ACCESS>
    juju add-relation neutron-hacluster neutron-api

## High availability

When more than one unit is deployed with the [hacluster][hacluster-charm]
application the charm will bring up an HA active/active cluster.

There are two mutually exclusive high availability options: using virtual IP(s)
or DNS. In both cases the hacluster subordinate charm is used to provide the
Corosync and Pacemaker backend HA functionality.

See [OpenStack high availability][cdg-ha-apps] in the [OpenStack Charms
Deployment Guide][cdg] for details.

# Restrictions

This charm only support deployment with OpenStack Icehouse or better.

# Internal DNS for Cloud Guests

The charm supports enabling internal DNS resolution for cloud guests in
accordance with the OpenStack DNS integration guide. To enable internal DNS
resolution, the 'enable-ml2-dns' option must be set to True. When enabled, the
domain name specified in the 'dns-domain' will be advertised as the nameserver
search path by the DHCP agents.

The Nova compute service will leverage this functionality when enabled. When
ports are allocated by the compute service, the dns_name of the port is
populated with a DNS sanitized version of the instance's display name. The
Neutron DHCP agents will then create host entries in the dnsmasq's
configuration files matching the dns_name of the port to the IP address
associated with the port.

Note that the DNS nameserver provided to the instance by the DHCP agent depends
on the tenant's network setup. The Neutron DHCP agent only advertises itself as
a nameserver when the Neutron subnet does not have nameservers configured. If
additional nameservers are needed and internal DNS is desired, then the IP
address of the DHCP port should be added to the subnet's list of configured
nameservers.

For more information refer to the OpenStack documentation on
[DNS Integration](https://docs.openstack.org/ocata/networking-guide/config-dns-int.html).

# External DNS for Cloud Guests

To add support for DNS record auto-generation when Neutron ports and floating
IPs are created the charm needs a relation with designate charm:

    juju deploy designate
    juju add-relation neutron-api designate

In order to enable the creation of reverse lookup (PTR) records, enable
"allow-reverse-dns-lookup" charm option:

    juju config neutron-api allow-reverse-dns-lookup=True

and configure the following charm options:

    juju config neutron-api ipv4-ptr-zone-prefix-size=<IPV4 PREFIX SIZE>
    juju config neutron-api ipv6-ptr-zone-prefix-size=<IPV6 PREFIX SIZE>

For example, if prefix sizes of your IPv4 and IPv6 subnets are "24" (e.g.
"192.168.0.0/24") and "64" (e.g. "fdcd:06ca:e498:216b::/64") respectively,
configure the charm options as follows:

    juju config neutron-api ipv4-ptr-zone-prefix-size=24
    juju config neutron-api ipv6-ptr-zone-prefix-size=64

For more information refer to the OpenStack documentation on
[DNS Integration](https://docs.openstack.org/ocata/networking-guide/config-dns-int.html)

# Spaces

This charm supports the use of Juju Network Spaces, allowing the charm to be
bound to network space configurations managed directly by Juju. This is only
supported with Juju 2.0 and above.

API endpoints can be bound to distinct network spaces supporting the network
separation of public, internal and admin endpoints.

Access to the underlying MySQL instance can also be bound to a specific space
using the shared-db relation.

To use this feature, use the --bind option when deploying the charm:

    juju deploy neutron-api --bind \
       "public=public-space \
        internal=internal-space \
        admin=admin-space \
        shared-db=internal-space"

Alternatively these can also be provided as part of a juju native
bundle configuration:

```yaml
    neutron-api:
      charm: cs:xenial/neutron-api
      num_units: 1
      bindings:
        public: public-space
        admin: admin-space
        internal: internal-space
        shared-db: internal-space
```

NOTE: Spaces must be configured in the underlying provider prior to attempting
to use them.

NOTE: Existing deployments using os-*-network configuration options will
continue to function; these options are preferred over any network space
binding provided if set.

# Additional Middleware Requests by Neutron Plugin Charms

Some neutron plugins may require additional middleware to be added to
api-paste.ini. In order to support that a subordinate may pass extra_middleware
via the neutron-plugin-api-subordinate relation.

Relation data to be set by subordinates:
    {'extra_middleware': [{
            'type': 'middleware_type',
            'name': 'middleware_name',
            'config': {
                'setting_1': 'value_1',
                'setting_2': 'value_2'}}]}

It would not be correct to do that from your own plugin as this requires the
neutron-api service restart which should be handled in this charm.

The developer guide for Neutron contains a description of the startup process
which makes it clear that api-paste.ini is parsed only once in neutron-api's
lifetime (see the "WSGI Application" section):

https://opendev.org/openstack/neutron/src/branch/master/doc/source/contributor/internals/api_layer.rst

For the api-paste.ini format in general, please consult PasteDeploy repository
docs/index.txt, "Config Format" section: https://github.com/Pylons/pastedeploy

Classes in loadwsgi.py contain config_prefixes that can be used for middleware
types - these are the prefixes the charm code validates passed data against:

https://github.com/Pylons/pastedeploy/blob/master/paste/deploy/loadwsgi.py

## Policy Overrides

Policy overrides is an **advanced** feature that allows an operator to override
the default policy of an OpenStack service. The policies that the service
supports, the defaults it implements in its code, and the defaults that a charm
may include should all be clearly understood before proceeding.

> **Caution**: It is possible to break the system (for tenants and other
  services) if policies are incorrectly applied to the service.

Policy statements are placed in a YAML file. This file (or files) is then (ZIP)
compressed into a single file and used as an application resource. The override
is then enabled via a Boolean charm option.

Here are the essential commands (filenames are arbitrary):

    zip overrides.zip override-file.yaml
    juju attach-resource neutron-api policyd-override=overrides.zip
    juju config neutron-api use-policyd-override=true

See appendix [Policy Overrides][cdg-appendix-n] in the [OpenStack Charms
Deployment Guide][cdg] for a thorough treatment of this feature.

# Bugs

Please report bugs on [Launchpad][lp-bugs-charm-neutron-api].

For general charm questions refer to the OpenStack [Charm Guide][cg].

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide
[cdg-appendix-n]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-policy-overrides.html
[lp-bugs-charm-neutron-api]: https://bugs.launchpad.net/charm-neutron-api/+filebug
[hacluster-charm]: https://jaas.ai/hacluster
[cdg-ha-apps]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide/latest/app-ha.html#ha-applications
