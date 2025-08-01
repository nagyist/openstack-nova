# Copyright 2014 IBM Corporation.  All rights reserved.
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
import copy

from nova.objects import external_event as external_event_obj

create = {
    'type': 'object',
    'properties': {
        'events': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'enum': [
                            'network-changed',
                            'network-vif-plugged',
                            'network-vif-unplugged',
                            'network-vif-deleted',
                        ],
                    },
                    'server_uuid': {
                        'type': 'string', 'format': 'uuid'
                    },
                    'status': {
                        'type': 'string',
                        'enum': external_event_obj.EVENT_STATUSES,
                    },
                    'tag': {
                        'type': 'string',
                        'maxLength': 255,
                    },
                },
                'required': ['name', 'server_uuid'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['events'],
    'additionalProperties': False,
}

create_v251 = copy.deepcopy(create)
name = create_v251['properties']['events']['items']['properties']['name']
name['enum'].append('volume-extended')

create_v276 = copy.deepcopy(create_v251)
name = create_v276['properties']['events']['items']['properties']['name']
name['enum'].append('power-update')

create_v282 = copy.deepcopy(create_v276)
name = create_v282['properties']['events']['items']['properties']['name']
name['enum'].append('accelerator-request-bound')

create_v293 = copy.deepcopy(create_v282)
name = create_v293['properties']['events']['items']['properties']['name']
name['enum'].append('volume-reimaged')

create_response = {
    'type': 'object',
    'properties': {
        'events': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'code': {
                        'type': 'integer',
                        'enum': [200, 400, 404, 422],
                    },
                    'name': {
                        'type': 'string',
                        'enum': [
                            'network-changed',
                            'network-vif-plugged',
                            'network-vif-unplugged',
                            'network-vif-deleted',
                        ],
                    },
                    'server_uuid': {'type': 'string', 'format': 'uuid'},
                    'status': {
                        'type': 'string',
                        'enum': external_event_obj.EVENT_STATUSES,
                    },
                    'tag': {
                        'type': 'string',
                        'maxLength': 255,
                    },
                },
                'required': [
                    'code',
                    'name',
                    'server_uuid',
                    'status',
                    # tag is not required in responses, although omitting it
                    # from requests will result in a failed event response
                ],
                'additionalProperties': False,
            },
        },
    },
    'required': ['events'],
    'additionalProperties': False,
}

create_response_v251 = copy.deepcopy(create_response)
name = create_response_v251['properties']['events']['items']['properties'][
    'name'
]
name['enum'].append('volume-extended')

create_response_v276 = copy.deepcopy(create_response_v251)
name = create_response_v276['properties']['events']['items']['properties'][
    'name'
]
name['enum'].append('power-update')

create_response_v282 = copy.deepcopy(create_response_v276)
name = create_response_v282['properties']['events']['items']['properties'][
    'name'
]
name['enum'].append('accelerator-request-bound')

create_response_v293 = copy.deepcopy(create_response_v282)
name = create_response_v293['properties']['events']['items']['properties'][
    'name'
]
name['enum'].append('volume-reimaged')
