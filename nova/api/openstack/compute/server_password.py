# Copyright (c) 2012 Nebula, Inc.
# All Rights Reserved.
#
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

"""The server password extension."""

from nova.api.metadata import password
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import server_password as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.policies import server_password as sp_policies


@validation.validated
class ServerPasswordController(wsgi.Controller):
    """The Server Password API controller for the OpenStack API."""

    def __init__(self):
        super(ServerPasswordController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.index_query)
    @validation.response_body_schema(schema.index_response)
    def index(self, req, server_id):
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(sp_policies.BASE_POLICY_NAME % 'show',
                    target={'project_id': instance.project_id})

        passw = password.extract_password(instance)
        return {'password': passw or ''}

    @wsgi.expected_errors(404)
    @wsgi.response(204)
    @validation.response_body_schema(schema.clear_response)
    def clear(self, req, server_id):
        """Removes the encrypted server password from the metadata server

        Note that this does not actually change the instance server
        password.
        """

        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(sp_policies.BASE_POLICY_NAME % 'clear',
                    target={'project_id': instance.project_id})
        meta = password.convert_password(context, None)
        instance.system_metadata.update(meta)
        instance.save()
