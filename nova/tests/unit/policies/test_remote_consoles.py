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

from unittest import mock

import fixtures
from nova.policies import remote_consoles as rc_policies
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import remote_consoles
from nova.compute import vm_states
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class RemoteConsolesPolicyTest(base.BasePolicyTest):
    """Test Remote Consoles APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(RemoteConsolesPolicyTest, self).setUp()
        self.controller = remote_consoles.RemoteConsolesController()
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "http://fake"}
        self.controller.handlers['vnc'] = mock_handler
        self.req = fakes.HTTPRequest.blank('', version='2.6')
        user_id = self.req.environ['nova.context'].user_id
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuid, project_id=self.project_id,
                user_id=user_id, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to get
        # server remote consoles.
        self.project_action_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context]

    def test_create_console_policy(self):
        rule_name = rc_policies.BASE_POLICY_NAME
        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        self.common_policy_auth(self.project_action_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, self.instance.uuid,
                                body=body)


class RemoteConsolesNoLegacyNoScopePolicyTest(RemoteConsolesPolicyTest):
    """Test Remote Consoles APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """
    without_deprecated_rules = True

    def setUp(self):
        super(RemoteConsolesNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, only project admin or member will be
        # able get server remote consoles.
        self.project_action_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)


class RemoteConsolesScopeTypePolicyTest(RemoteConsolesPolicyTest):
    """Test Remote Consoles APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(RemoteConsolesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # Scope enable will not allow system admin to get server
        # remote console.
        self.project_action_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)


class RemoteConsolesScopeTypeNoLegacyPolicyTest(
        RemoteConsolesScopeTypePolicyTest):
    """Test Remote Consoles APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(RemoteConsolesScopeTypeNoLegacyPolicyTest, self).setUp()
        # With scope enable and no legacy rule, only project admin/member
        # will be able to get server remote console.
        self.project_action_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)
