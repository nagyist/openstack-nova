#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import ips
from nova.compute import vm_states
from nova.policies import ips as ips_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerIpsPolicyTest(base.BasePolicyTest):
    """Test Server IPs APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerIpsPolicyTest, self).setUp()
        self.controller = ips.IPsController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuid, project_id=self.project_id,
                vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        self.mock_get_network = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common'
                '.get_networks_for_instance')).mock
        self.mock_get_network.return_value = {'net1':
            {'ips': '', 'floating_ips': ''}}

        # With legacy rule, any admin or project role is able to get their
        # server IP addresses.
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context,
        ]

    def test_index_ips_policy(self):
        rule_name = ips_policies.POLICY_ROOT % 'index'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req, self.instance.uuid)

    def test_show_ips_policy(self):
        rule_name = ips_policies.POLICY_ROOT % 'show'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, self.instance.uuid,
                                'net1')


class ServerIpsNoLegacyNoScopePolicyTest(ServerIpsPolicyTest):
    """Test Server Ips APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerIpsNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy, only project admin, member, and reader will be able
        # to get their server IP addresses.
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_no_scope_no_legacy)


class ServerIpsScopeTypePolicyTest(ServerIpsPolicyTest):
    """Test Server IPs APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerIpsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With scope enabled, system users will not be able
        # to get the server IP addresses.
        self.project_reader_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)


class ServerIpsScopeTypeNoLegacyPolicyTest(ServerIpsScopeTypePolicyTest):
    """Test Server IPs APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerIpsScopeTypeNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enable, only admin, member,
        # and reader will be able to get their server IP addresses.
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_scope_no_legacy)
