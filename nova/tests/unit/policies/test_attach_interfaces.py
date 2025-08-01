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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import attach_interfaces
from nova.compute import vm_states
from nova import exception
from nova.policies import attach_interfaces as ai_policies
from nova.policies import base as base_policy
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class AttachInterfacesPolicyTest(base.BasePolicyTest):
    """Test Attach Interfaces APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AttachInterfacesPolicyTest, self).setUp()
        self.controller = attach_interfaces.InterfaceAttachmentController()
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
        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to attach,
        # detach an interface from a server.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context]
        # and they can get their own server attached interfaces.
        self.project_reader_authorized_contexts = (
            self.project_member_authorized_contexts)

    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.network.neutron.API.list_ports')
    def test_index_interfaces_policy(self, mock_port, mock_get):
        rule_name = "os_compute_api:os-attach-interfaces:list"
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req, uuids.fake_id)

    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.network.neutron.API.show_port')
    def test_show_interface_policy(self, mock_port, mock_get):
        rule_name = "os_compute_api:os-attach-interfaces:show"
        server_id = uuids.fake_id
        port_id = uuids.fake_id
        mock_port.return_value = {'port': {
            "id": port_id,
            "network_id": uuids.fake_id,
            "admin_state_up": True,
            "status": "ACTIVE",
            "mac_address": "bb:bb:bb:bb:bb:bb",
            "fixed_ips": [
                {
                    "ip_address": "10.0.2.2",
                    "subnet_id": uuids.subnet_id,
                },
            ],
            "device_id": server_id,
        }}
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, server_id, port_id)

    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.network.neutron.API.show_port')
    @mock.patch('nova.compute.api.API.attach_interface')
    def test_attach_interface(self, mock_interface, mock_port, mock_get):
        rule_name = "os_compute_api:os-attach-interfaces:create"
        server_id = uuids.fake_id
        mock_port.return_value = {'port': {
            "id": uuids.port_id,
            "network_id": uuids.fake_id,
            "admin_state_up": True,
            "status": "ACTIVE",
            "mac_address": "bb:bb:bb:bb:bb:bb",
            "fixed_ips": [
                {
                    "ip_address": "10.0.2.2",
                    "subnet_id": uuids.subnet_id,
                },
            ],
            "device_id": server_id,
        }}
        body = {'interfaceAttachment': {'net_id': uuids.fake_id}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, server_id, body=body)

    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.compute.api.API.detach_interface')
    def test_delete_interface(self, mock_detach, mock_get):
        rule_name = "os_compute_api:os-attach-interfaces:delete"
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name, self.controller.delete,
                                self.req, uuids.fake_id, uuids.fake_id)


class AttachInterfacesNoLegacyNoScopePolicyTest(AttachInterfacesPolicyTest):
    """Test Attach Interfaces APIs policies with no legacy deprecated rules
    and no scope checks.

    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        ai_policies.POLICY_ROOT % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(AttachInterfacesNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, legacy admin loose power.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_no_scope_no_legacy)


class AttachInterfacesScopeTypePolicyTest(AttachInterfacesPolicyTest):
    """Test Attach Interfaces APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AttachInterfacesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With Scope enable, system users no longer allowed.
        self.project_member_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)
        self.project_reader_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)


class AttachInterfacesDeprecatedPolicyTest(base.BasePolicyTest):
    """Test Attach Interfaces APIs Deprecated policies.
    This class checks if deprecated policy rules are
    overridden by user on policy.yaml file then they
    still work because oslo.policy add deprecated rules
    in logical OR condition and enforce them for policy
    checks if overridden.
    """

    def setUp(self):
        super(AttachInterfacesDeprecatedPolicyTest, self).setUp()
        self.controller = attach_interfaces.InterfaceAttachmentController()
        self.admin_req = fakes.HTTPRequest.blank('')
        self.admin_req.environ['nova.context'] = self.project_admin_context
        self.reader_req = fakes.HTTPRequest.blank('')
        self.reader_req.environ['nova.context'] = self.project_reader_context
        self.deprecated_policy = "os_compute_api:os-attach-interfaces"
        # Override rule with different checks than defaults so that we can
        # verify the rule overridden case.
        override_rules = {self.deprecated_policy: base_policy.RULE_ADMIN_API}
        # NOTE(gmann): Only override the deprecated rule in policy file so
        # that
        # we can verify if overridden checks are considered by oslo.policy.
        # Oslo.policy will consider the overridden rules if:
        #  1. overridden deprecated rule's checks are different than defaults
        #  2. new rules are not present in policy file
        self.policy = self.useFixture(nova_fixtures.OverridePolicyFixture(
                                      rules_in_file=override_rules))

    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.network.neutron.API.list_ports')
    def test_deprecated_policy_overridden_rule_is_checked(self, mock_port,
                                                          mock_get):
        # Test to verify if deprecated overridden policy is working.

        # check for success as admin role. Deprecated rule
        # has been overridden with admin checks in policy.yaml
        # If admin role pass it means overridden rule is enforced by
        # oslo.policy because new default is system or project reader and the
        # old default is admin.
        self.controller.index(self.admin_req, uuids.fake_id)

        # check for failure with reader context.
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.index, self.reader_req,
                                uuids.fake_id)
        self.assertEqual(
            "Policy doesn't allow os_compute_api:os-attach-interfaces:list"
            " to be performed.",
            exc.format_message())


class AttachInterfacesScopeTypeNoLegacyPolicyTest(
        AttachInterfacesScopeTypePolicyTest):
    """Test Attach Interfaces APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        ai_policies.POLICY_ROOT % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        ai_policies.POLICY_ROOT % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(AttachInterfacesScopeTypeNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enable, only project admin, member,
        # and reader will be able to allowed operation on server interface.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_scope_no_legacy)
