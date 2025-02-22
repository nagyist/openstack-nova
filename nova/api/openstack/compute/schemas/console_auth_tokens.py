# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

show_response = {
    'type': 'object',
    'properties': {
        'console': {
            'type': 'object',
            'properties': {
                'instance_uuid': {'type': 'string', 'format': 'uuid'},
                'host': {'type': ['string', 'null']},
                'port': {'type': 'integer'},
                'internal_access_path': {
                    'oneOf': [
                        {
                            'type': 'null',
                        },
                        {
                            'type': 'string',
                            'format': 'uuid',
                        },
                    ],
                },
            },
            'required': [
                'instance_uuid', 'host', 'port', 'internal_access_path',
            ],
            'additionalProperties': False,
        },
    },
    'required': ['console'],
    'additionalProperties': False,
}
