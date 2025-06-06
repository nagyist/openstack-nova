# Copyright 2019 INSPUR Corporation.  All rights reserved.
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

from nova.api.validation import parameter_types

# TODO(stephenfin): Restrict the value to 'null' in a future API version
shelve = {
    'type': 'object',
    'properties': {
        'shelve': {},
    },
    'required': ['shelve'],
    'additionalProperties': False,
}

# TODO(stephenfin): Restrict the value to 'null' in a future API version
shelve_offload = {
    'type': 'object',
    'properties': {
        'shelveOffload': {},
    },
    'required': ['shelveOffload'],
    'additionalProperties': False,
}

unshelve = {
    'type': 'object',
    'properties': {
        'unshelve': {},
    },
    'required': ['unshelve'],
    'additionalProperties': False,
}

# NOTE(brinzhang): For older microversion there will be no change as
# schema is applied only for version < 2.91 with unshelve a server API.
# Anything working in old version keep working as it is.
unshelve_v277 = {
    'type': 'object',
    'properties': {
        'unshelve': {
            'type': ['object', 'null'],
            'properties': {
                'availability_zone': parameter_types.name
            },
            # NOTE: The allowed request body is {'unshelve': null} or
            # {'unshelve': {'availability_zone': <string>}}, not allowed
            # {'unshelve': {}} as the request body for unshelve.
            'required': ['availability_zone'],
            'additionalProperties': False,
        },
    },
    'required': ['unshelve'],
    'additionalProperties': False,
}

# NOTE(rribaud):
# schema is applied only for version >= 2.91 with unshelve a server API.
# Add host parameter to specify to unshelve to this specific host.
#
# Schema has been redefined for better clarity instead of extend 2.77.
#
# API can be called with the following body:
#
# - {"unshelve": null}   (Keep compatibility with previous microversions)
#
# or
#
# - {"unshelve": {"availability_zone": <string>}}
# - {"unshelve": {"availability_zone": null}}   (Unpin availability zone)
# - {"unshelve": {"host": <fqdn>}}
# - {"unshelve": {"availability_zone": <string>, "host": <fqdn>}}
# - {"unshelve": {"availability_zone": null, "host": <fqdn>}}
#
#
# Everything else is not allowed, examples:
#
# - {"unshelve": {}}
# - {"unshelve": {"host": <fqdn>, "host": <fqdn>}}
# - {"unshelve": {"foo": <string>}}

unshelve_v291 = {
    "type": "object",
    "properties": {
        "unshelve": {
            "type": ["object", "null"],
            "properties": {
                "availability_zone": {
                    "type": ["string", "null"],
                },
                "host": {
                    "type": "string"
                }
            },
            "additionalProperties": False,
        }
    },
    "required": ["unshelve"],
    "additionalProperties": False,
}

shelve_response = {
    'type': 'null',
}

shelve_offload_response = {
    'type': 'null',
}

unshelve_response = {
    'type': 'null',
}
