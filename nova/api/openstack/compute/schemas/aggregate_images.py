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

from nova.api.validation import parameter_types


aggregate_images = {
    'type': 'object',
    'properties': {
        'cache': {
            'type': ['array'],
            'minItems': 1,
            'items': {
                'type': 'object',
                'properties': {
                    'id': parameter_types.image_id,
                },
                'additionalProperties': False,
                'required': ['id'],
            },
        },
    },
    'required': ['cache'],
    'additionalProperties': False,
}

aggregate_images_response = {
    'type': 'null',
}
