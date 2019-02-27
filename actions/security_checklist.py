#!/usr/bin/env python3
#
# Copyright 2019 Canonical Ltd
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

import configparser
import sys

sys.path.append('hooks')

import charmhelpers.contrib.openstack.audits as audits
from charmhelpers.contrib.openstack.audits import (
    openstack_security_guide,
)


# Via the openstack_security_guide above, we are running the following
# security assertions automatically:
#
# - Check-Neutron-01 - validate-file-ownership
# - Check-Neutron-02 - validate-file-permissions
# - Check-Neutron-03 - validate-uses-keystone
# - Check-Neutron-04 - validate-uses-tls-for-keystone

@audits.audit(audits.is_audit_type(audits.AuditType.OpenStackSecurityGuide))
def validate_enables_tls(audit_options):
    """Verify that TLS is enabled on Neutron.

    Security Guide Check Name: Check-Neutron-05

    :param audit_options: Dictionary of options for audit configuration
    :type audit_options: Dict
    :raises: AssertionError if the assertion fails.
    """
    section = audit_options['neutron_config']['DEFAULT']
    assert section.get('use_ssl') == "True", \
        "SSL should be enabled on neutron-api"


def main():
    config = {
        'config_path': '/etc/neutron',
        'config_file': 'neutron.conf',
        'audit_type': audits.AuditType.OpenStackSecurityGuide,
        'files': openstack_security_guide.FILE_ASSERTIONS['neutron-api'],
        'excludes': [
            'validate-uses-tls-for-glance',
        ],
    }
    conf = configparser.ConfigParser()
    conf.read("/etc/neutron/neutron.conf")
    config['neutron_config'] = dict(conf)
    return audits.action_parse_results(audits.run(config))

if __name__ == "__main__":
    sys.exit(main())
