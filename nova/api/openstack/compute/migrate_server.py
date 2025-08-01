# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import migrate_server as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.policies import migrate_server as ms_policies

LOG = logging.getLogger(__name__)


@validation.validated
class MigrateServerController(wsgi.Controller):
    def __init__(self):
        super(MigrateServerController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('migrate')
    @validation.schema(schema.migrate, "2.56")
    @validation.response_body_schema(schema.migrate_response)
    def _migrate(self, req, id, body):
        """Permit admins to migrate a server to a new host."""
        context = req.environ['nova.context']

        instance = common.get_instance(self.compute_api, context, id,
                                       expected_attrs=['flavor', 'services'])
        host_name = None
        if (
            api_version_request.is_supported(req, '2.56') and
            body['migrate'] is not None
        ):
            host_name = body['migrate'].get('host')

        if host_name:
            context.can(ms_policies.POLICY_ROOT % 'migrate:host',
                        target={'project_id': instance.project_id})
        else:
            context.can(ms_policies.POLICY_ROOT % 'migrate',
                        target={'project_id': instance.project_id})
        try:
            self.compute_api.resize(req.environ['nova.context'], instance,
                                    host_name=host_name)
        except exception.OverQuota as e:
            raise exc.HTTPForbidden(explanation=e.format_message())
        except (
            exception.InstanceIsLocked,
            exception.InstanceNotReady,
            exception.ServiceUnavailable,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'migrate', id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (
            exception.ComputeHostNotFound,
            exception.CannotMigrateToSameHost,
            exception.ForbiddenPortsWithAccelerator,
            exception.ExtendedResourceRequestOldCompute,
        ) as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except (
            exception.ForbiddenSharesNotSupported,
            exception.ForbiddenWithShare,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('os-migrateLive')
    @validation.schema(schema.migrate_live, "2.0", "2.24")
    @validation.schema(schema.migrate_live_v2_25, "2.25", "2.29")
    @validation.schema(schema.migrate_live_v2_30, "2.30", "2.67")
    @validation.schema(schema.migrate_live_v2_68, "2.68")
    @validation.response_body_schema(schema.migrate_live_response)
    def _migrate_live(self, req, id, body):
        """Permit admins to (live) migrate a server to a new host."""
        context = req.environ["nova.context"]

        # NOTE(stephenfin): we need 'numa_topology' because of the
        # 'LiveMigrationTask._check_instance_has_no_numa' check in the
        # conductor
        instance = common.get_instance(self.compute_api, context, id,
                                       expected_attrs=['numa_topology'])

        host = body["os-migrateLive"]["host"]
        if host:
            context.can(ms_policies.POLICY_ROOT % 'migrate_live:host',
                        target={'project_id': instance.project_id})
        else:
            context.can(ms_policies.POLICY_ROOT % 'migrate_live',
                        target={'project_id': instance.project_id})

        block_migration = body["os-migrateLive"]["block_migration"]
        force = None
        async_ = api_version_request.is_supported(req, '2.34')
        if api_version_request.is_supported(req, '2.30'):
            force = self._get_force_param_for_live_migration(body, host)
        if api_version_request.is_supported(req, '2.25'):
            if block_migration == 'auto':
                block_migration = None
            else:
                block_migration = strutils.bool_from_string(block_migration,
                                                            strict=True)
            disk_over_commit = None
        else:
            disk_over_commit = body["os-migrateLive"]["disk_over_commit"]

            block_migration = strutils.bool_from_string(block_migration,
                                                        strict=True)
            disk_over_commit = strutils.bool_from_string(disk_over_commit,
                                                         strict=True)

        try:
            self.compute_api.live_migrate(context, instance, block_migration,
                                          disk_over_commit, host, force,
                                          async_)
        except (exception.NoValidHost,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.MigrationPreCheckError,
                exception.ForbiddenPortsWithAccelerator) as ex:
            if async_:
                with excutils.save_and_reraise_exception():
                    LOG.error("Unexpected exception received from "
                              "conductor during pre-live-migration checks "
                              "'%(ex)s'", {'ex': ex})
            else:
                raise exc.HTTPBadRequest(explanation=ex.format_message())
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except (
            exception.ComputeHostNotFound,
            exception.ExtendedResourceRequestOldCompute,
        )as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'os-migrateLive', id)
        except (
            exception.ForbiddenSharesNotSupported,
            exception.ForbiddenWithShare,
        ) as e:
            raise exc.HTTPConflict(explanation=e.format_message())

    def _get_force_param_for_live_migration(self, body, host):
        force = body["os-migrateLive"].get("force", False)
        force = strutils.bool_from_string(force, strict=True)
        if force is True and not host:
            message = _("Can't force to a non-provided destination")
            raise exc.HTTPBadRequest(explanation=message)
        return force
