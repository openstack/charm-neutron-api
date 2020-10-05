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
import json
import uuid

from . import utils


class SimpleOVSDB(object):
    """Simple interface to OVSDB through the use of command line tools.

    OVS and OVN is managed through a set of databases.  These databases have
    similar command line tools to manage them.  We make use of the similarity
    to provide a generic class that can be used to manage them.

    The OpenvSwitch project does provide a Python API, but on the surface it
    appears to be a bit too involved for our simple use case.

    Examples:
    sbdb = SimpleOVSDB('ovn-sbctl')
    for chs in sbdb.chassis:
        print(chs)

    ovsdb = SimpleOVSDB('ovs-vsctl')
    for br in ovsdb.bridge:
        if br['name'] == 'br-test':
            ovsdb.bridge.set(br['uuid'], 'external_ids:charm', 'managed')
    """

    # For validation we keep a complete map of currently known good tool and
    # table combinations.  This requires maintenance down the line whenever
    # upstream adds things that downstream wants, and the cost of maintaining
    # that will most likely be lower then the cost of finding the needle in
    # the haystack whenever downstream code misspells something.
    _tool_table_map = {
        'ovs-vsctl': (
            'autoattach',
            'bridge',
            'ct_timeout_policy',
            'ct_zone',
            'controller',
            'datapath',
            'flow_sample_collector_set',
            'flow_table',
            'ipfix',
            'interface',
            'manager',
            'mirror',
            'netflow',
            'open_vswitch',
            'port',
            'qos',
            'queue',
            'ssl',
            'sflow',
        ),
        'ovn-nbctl': (
            'acl',
            'address_set',
            'connection',
            'dhcp_options',
            'dns',
            'forwarding_group',
            'gateway_chassis',
            'ha_chassis',
            'ha_chassis_group',
            'load_balancer',
            'load_balancer_health_check',
            'logical_router',
            'logical_router_policy',
            'logical_router_port',
            'logical_router_static_route',
            'logical_switch',
            'logical_switch_port',
            'meter',
            'meter_band',
            'nat',
            'nb_global',
            'port_group',
            'qos',
            'ssl',
        ),
        'ovn-sbctl': (
            'address_set',
            'chassis',
            'connection',
            'controller_event',
            'dhcp_options',
            'dhcpv6_options',
            'dns',
            'datapath_binding',
            'encap',
            'gateway_chassis',
            'ha_chassis',
            'ha_chassis_group',
            'igmp_group',
            'ip_multicast',
            'logical_flow',
            'mac_binding',
            'meter',
            'meter_band',
            'multicast_group',
            'port_binding',
            'port_group',
            'rbac_permission',
            'rbac_role',
            'sb_global',
            'ssl',
            'service_monitor',
        ),
    }

    def __init__(self, tool):
        """SimpleOVSDB constructor.

        :param tool: Which tool with database commands to operate on.
                     Usually one of `ovs-vsctl`, `ovn-nbctl`, `ovn-sbctl`
        :type tool: str
        """
        if tool not in self._tool_table_map:
            raise RuntimeError(
                'tool must be one of "{}"'.format(self._tool_table_map.keys()))
        self._tool = tool

    def __getattr__(self, table):
        if table not in self._tool_table_map[self._tool]:
            raise AttributeError(
                'table "{}" not known for use with "{}"'
                .format(table, self._tool))
        return self.Table(self._tool, table)

    class Table(object):
        """Methods to interact with contents of OVSDB tables.

        NOTE: At the time of this writing ``find`` is the only command
        line argument to OVSDB manipulating tools that actually supports
        JSON output.
        """

        def __init__(self, tool, table):
            """SimpleOVSDBTable constructor.

            :param table: Which table to operate on
            :type table: str
            """
            self._tool = tool
            self._table = table

        def _find_tbl(self, condition=None):
            """Run and parse output of OVSDB `find` command.

            :param condition: An optional RFC 7047 5.1 match condition
            :type condition: Optional[str]
            :returns: Dictionary with data
            :rtype: Dict[str, any]
            """
            # When using json formatted output to OVS commands Internal OVSDB
            # notation may occur that require further deserializing.
            # Reference: https://tools.ietf.org/html/rfc7047#section-5.1
            ovs_type_cb_map = {
                'uuid': uuid.UUID,
                # FIXME sets also appear to sometimes contain type/value tuples
                'set': list,
                'map': dict,
            }
            cmd = [self._tool, '-f', 'json', 'find', self._table]
            if condition:
                cmd.append(condition)
            output = utils._run(*cmd)
            data = json.loads(output)
            for row in data['data']:
                values = []
                for col in row:
                    if isinstance(col, list):
                        f = ovs_type_cb_map.get(col[0], str)
                        values.append(f(col[1]))
                    else:
                        values.append(col)
                yield dict(zip(data['headings'], values))

        def __iter__(self):
            return self._find_tbl()

        def clear(self, rec, col):
            utils._run(self._tool, 'clear', self._table, rec, col)

        def find(self, condition):
            return self._find_tbl(condition=condition)

        def remove(self, rec, col, value):
            utils._run(self._tool, 'remove', self._table, rec, col, value)

        def set(self, rec, col, value):
            utils._run(self._tool, 'set', self._table, rec,
                       '{}={}'.format(col, value))
