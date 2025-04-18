# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Instance Metadata information."""

import itertools
import os
import posixpath

from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova.api.metadata import password
from nova.api.metadata import vendordata_dynamic
from nova.api.metadata import vendordata_json
from nova import block_device
import nova.conf
from nova import context
from nova import exception
from nova.network import neutron
from nova.network import security_group_api
from nova import objects
from nova.objects import virt_device_metadata as metadata_obj
from nova import utils
from nova.virt import netutils


CONF = nova.conf.CONF

VERSIONS = [
    '1.0',
    '2007-01-19',
    '2007-03-01',
    '2007-08-29',
    '2007-10-10',
    '2007-12-15',
    '2008-02-01',
    '2008-09-01',
    '2009-04-04',
]

# NOTE(mikal): think of these strings as version numbers. They traditionally
# correlate with OpenStack release dates, with all the changes for a given
# release bundled into a single version. Note that versions in the future are
# hidden from the listing, but can still be requested explicitly, which is
# required for testing purposes. We know this isn't great, but its inherited
# from EC2, which this needs to be compatible with.
# NOTE(jichen): please update doc/source/user/metadata.rst on the metadata
# output when new version is created in order to make doc up-to-date.
FOLSOM = '2012-08-10'
GRIZZLY = '2013-04-04'
HAVANA = '2013-10-17'
LIBERTY = '2015-10-15'
NEWTON_ONE = '2016-06-30'
NEWTON_TWO = '2016-10-06'
OCATA = '2017-02-22'
ROCKY = '2018-08-27'
VICTORIA = '2020-10-14'
EPOXY = '2025-04-04'

OPENSTACK_VERSIONS = [
    FOLSOM,
    GRIZZLY,
    HAVANA,
    LIBERTY,
    NEWTON_ONE,
    NEWTON_TWO,
    OCATA,
    ROCKY,
    VICTORIA,
    EPOXY,
]

VERSION = "version"
CONTENT = "content"
CONTENT_DIR = "content"
MD_JSON_NAME = "meta_data.json"
VD_JSON_NAME = "vendor_data.json"
VD2_JSON_NAME = "vendor_data2.json"
NW_JSON_NAME = "network_data.json"
UD_NAME = "user_data"
PASS_NAME = "password"
MIME_TYPE_TEXT_PLAIN = "text/plain"
MIME_TYPE_APPLICATION_JSON = "application/json"

LOG = logging.getLogger(__name__)


class InvalidMetadataVersion(Exception):
    pass


class InvalidMetadataPath(Exception):
    pass


class InstanceMetadata(object):
    """Instance metadata."""

    def __init__(self, instance, address=None, content=None, extra_md=None,
                 network_info=None, network_metadata=None):
        """Creation of this object should basically cover all time consuming
        collection.  Methods after that should not cause time delays due to
        network operations or lengthy cpu operations.

        The user should then get a single instance and make multiple method
        calls on it.
        """
        if not content:
            content = []

        # NOTE(gibi): this is not a cell targeted context even if we are called
        # in a situation when the instance is in a different cell than the
        # metadata service itself.
        ctxt = context.get_admin_context()

        self.mappings = _format_instance_mapping(instance)

        # NOTE(danms): Sanitize the instance to limit the amount of stuff
        # inside that may not pickle well (i.e. context). We also touch
        # some of the things we'll lazy load later to make sure we keep their
        # values in what we cache.
        instance.ec2_ids
        instance.keypairs
        instance.device_metadata
        instance.numa_topology
        instance = objects.Instance.obj_from_primitive(
            instance.obj_to_primitive())

        # The default value of mimeType is set to MIME_TYPE_TEXT_PLAIN
        self.set_mimetype(MIME_TYPE_TEXT_PLAIN)
        self.instance = instance
        self.extra_md = extra_md

        self.availability_zone = instance.get('availability_zone')

        self.security_groups = security_group_api.get_instance_security_groups(
            ctxt, instance)

        if instance.user_data is not None:
            self.userdata_raw = base64.decode_as_bytes(instance.user_data)
        else:
            self.userdata_raw = None

        self.address = address

        # expose instance metadata.
        self.launch_metadata = utils.instance_meta(instance)

        self.password = password.extract_password(instance)

        self.uuid = instance.uuid

        self.content = {}
        self.files = []

        # get network info, and the rendered network template
        if network_info is None:
            network_info = instance.info_cache.network_info

        # expose network metadata
        if network_metadata is None:
            self.network_metadata = netutils.get_network_metadata(network_info)
        else:
            self.network_metadata = network_metadata

        self.ip_info = netutils.get_ec2_ip_info(network_info)

        self.network_config = None
        cfg = netutils.get_injected_network_template(network_info)

        if cfg:
            key = "%04i" % len(self.content)
            self.content[key] = cfg
            self.network_config = {"name": "network_config",
                'content_path': "/%s/%s" % (CONTENT_DIR, key)}

        # 'content' is passed in from the configdrive code in
        # nova/virt/libvirt/driver.py.  That's how we get the injected files
        # (personalities) in. AFAIK they're not stored in the db at all,
        # so are not available later (web service metadata time).
        for (path, contents) in content:
            key = "%04i" % len(self.content)
            self.files.append({'path': path,
                'content_path': "/%s/%s" % (CONTENT_DIR, key)})
            self.content[key] = contents

        self.route_configuration = None

        # NOTE(mikal): the decision to not pass extra_md here like we
        # do to the StaticJSON driver is deliberate. extra_md will
        # contain the admin password for the instance, and we shouldn't
        # pass that to external services.
        self.vendordata_providers = {
            'StaticJSON': vendordata_json.JsonFileVendorData(),
            'DynamicJSON': vendordata_dynamic.DynamicVendorData(
                instance=instance)
        }

    def _route_configuration(self):
        if self.route_configuration:
            return self.route_configuration

        path_handlers = {UD_NAME: self._user_data,
                         PASS_NAME: self._password,
                         VD_JSON_NAME: self._vendor_data,
                         VD2_JSON_NAME: self._vendor_data2,
                         MD_JSON_NAME: self._metadata_as_json,
                         NW_JSON_NAME: self._network_data,
                         VERSION: self._handle_version,
                         CONTENT: self._handle_content}

        self.route_configuration = RouteConfiguration(path_handlers)
        return self.route_configuration

    def set_mimetype(self, mime_type):
        self.md_mimetype = mime_type

    def get_mimetype(self):
        return self.md_mimetype

    def get_ec2_metadata(self, version):
        if version == "latest":
            version = VERSIONS[-1]

        if version not in VERSIONS:
            raise InvalidMetadataVersion(version)

        hostname = self._get_hostname()

        floating_ips = self.ip_info['floating_ips']
        floating_ip = floating_ips and floating_ips[0] or ''

        fixed_ips = self.ip_info['fixed_ips']
        fixed_ip = fixed_ips and fixed_ips[0] or ''

        fmt_sgroups = [x['name'] for x in self.security_groups]

        meta_data = {
            'ami-id': self.instance.ec2_ids.ami_id,
            'ami-launch-index': self.instance.launch_index,
            'ami-manifest-path': 'FIXME',
            'instance-id': self.instance.ec2_ids.instance_id,
            'hostname': hostname,
            'local-ipv4': fixed_ip or self.address,
            'reservation-id': self.instance.reservation_id,
            'security-groups': fmt_sgroups}

        # public keys are strangely rendered in ec2 metadata service
        #  meta-data/public-keys/ returns '0=keyname' (with no trailing /)
        # and only if there is a public key given.
        # '0=keyname' means there is a normally rendered dict at
        #  meta-data/public-keys/0
        #
        # meta-data/public-keys/ : '0=%s' % keyname
        # meta-data/public-keys/0/ : 'openssh-key'
        # meta-data/public-keys/0/openssh-key : '%s' % publickey
        if self.instance.key_name:
            meta_data['public-keys'] = {
                '0': {'_name': "0=" + self.instance.key_name,
                      'openssh-key': self.instance.key_data}}

        if self._check_version('2007-01-19', version):
            meta_data['local-hostname'] = hostname
            meta_data['public-hostname'] = hostname
            meta_data['public-ipv4'] = floating_ip

        if self._check_version('2007-08-29', version):
            flavor = self.instance.get_flavor()
            meta_data['instance-type'] = flavor['name']

        if self._check_version('2007-12-15', version):
            meta_data['block-device-mapping'] = self.mappings
            if self.instance.ec2_ids.kernel_id:
                meta_data['kernel-id'] = self.instance.ec2_ids.kernel_id
            if self.instance.ec2_ids.ramdisk_id:
                meta_data['ramdisk-id'] = self.instance.ec2_ids.ramdisk_id

        if self._check_version('2008-02-01', version):
            meta_data['placement'] = {'availability-zone':
                                      self.availability_zone}

        if self._check_version('2008-09-01', version):
            meta_data['instance-action'] = 'none'

        data = {'meta-data': meta_data}
        if self.userdata_raw is not None:
            data['user-data'] = self.userdata_raw

        return data

    def get_ec2_item(self, path_tokens):
        # get_ec2_metadata returns dict without top level version
        data = self.get_ec2_metadata(path_tokens[0])
        return find_path_in_tree(data, path_tokens[1:])

    def get_openstack_item(self, path_tokens):
        if path_tokens[0] == CONTENT_DIR:
            return self._handle_content(path_tokens)
        return self._route_configuration().handle_path(path_tokens)

    def _metadata_as_json(self, version, path):
        metadata = {'uuid': self.uuid}
        if self.launch_metadata:
            metadata['meta'] = self.launch_metadata
        if self.files:
            metadata['files'] = self.files
        if self.extra_md:
            metadata.update(self.extra_md)
        if self.network_config:
            metadata['network_config'] = self.network_config

        if self.instance.key_name:
            keypairs = self.instance.keypairs
            # NOTE(mriedem): It's possible for the keypair to be deleted
            # before it was migrated to the instance_extra table, in which
            # case lazy-loading instance.keypairs will handle the 404 and
            # just set an empty KeyPairList object on the instance.
            keypair = keypairs[0] if keypairs else None

            if keypair:
                metadata['public_keys'] = {
                    keypair.name: keypair.public_key,
                }

                metadata['keys'] = [
                    {'name': keypair.name,
                     'type': keypair.type,
                     'data': keypair.public_key}
                ]
            else:
                LOG.debug("Unable to find keypair for instance with "
                          "key name '%s'.", self.instance.key_name,
                          instance=self.instance)

        metadata['hostname'] = self._get_hostname()
        metadata['name'] = self.instance.display_name
        metadata['launch_index'] = self.instance.launch_index
        metadata['availability_zone'] = self.availability_zone

        if self._check_os_version(GRIZZLY, version):
            metadata['random_seed'] = base64.encode_as_text(os.urandom(512))

        if self._check_os_version(LIBERTY, version):
            metadata['project_id'] = self.instance.project_id

        if self._check_os_version(NEWTON_ONE, version):
            metadata['devices'] = self._get_device_metadata(version)

        if self._check_os_version(VICTORIA, version):
            metadata['dedicated_cpus'] = self._get_instance_dedicated_cpus()

        self.set_mimetype(MIME_TYPE_APPLICATION_JSON)
        return jsonutils.dump_as_bytes(metadata)

    def _get_device_metadata(self, version):
        """Build a device metadata dict based on the metadata objects. This is
        done here in the metadata API as opposed to in the objects themselves
        because the metadata dict is part of the guest API and thus must be
        controlled.
        """
        device_metadata_list = []
        vif_vlans_supported = self._check_os_version(OCATA, version)
        vif_vfs_trusted_supported = self._check_os_version(ROCKY, version)
        if self.instance.device_metadata is not None:
            for device in self.instance.device_metadata.devices:
                device_metadata = {}
                bus = 'none'
                address = 'none'

                if 'bus' in device:
                    # TODO(artom/mriedem) It would be nice if we had something
                    # more generic, like a type identifier or something, built
                    # into these types of objects, like a get_meta_type()
                    # abstract method on the base DeviceBus class.
                    if isinstance(device.bus, metadata_obj.PCIDeviceBus):
                        bus = 'pci'
                    elif isinstance(device.bus, metadata_obj.USBDeviceBus):
                        bus = 'usb'
                    elif isinstance(device.bus, metadata_obj.SCSIDeviceBus):
                        bus = 'scsi'
                    elif isinstance(device.bus, metadata_obj.IDEDeviceBus):
                        bus = 'ide'
                    elif isinstance(device.bus, metadata_obj.XenDeviceBus):
                        bus = 'xen'
                    else:
                        LOG.debug('Metadata for device with unknown bus %s '
                                  'has not been included in the '
                                  'output', device.bus.__class__.__name__)
                        continue
                    if 'address' in device.bus:
                        address = device.bus.address

                if isinstance(device, metadata_obj.NetworkInterfaceMetadata):
                    vlan = device.vlan if 'vlan' in device else None
                    if vif_vlans_supported and vlan is not None:
                        device_metadata['vlan'] = vlan
                    if vif_vfs_trusted_supported:
                        vf_trusted = (device.vf_trusted if
                                      'vf_trusted' in device else False)
                        device_metadata['vf_trusted'] = vf_trusted
                    device_metadata['type'] = 'nic'
                    device_metadata['mac'] = device.mac
                    # NOTE(artom) If a device has neither tags, vlan or
                    # vf_trusted, don't expose it
                    if not ('tags' in device or 'vlan' in device_metadata or
                            'vf_trusted' in device_metadata):
                        continue
                elif isinstance(device, metadata_obj.DiskMetadata):
                    device_metadata['type'] = 'disk'
                    # serial and path are optional parameters
                    if 'serial' in device:
                        device_metadata['serial'] = device.serial
                    if 'path' in device:
                        device_metadata['path'] = device.path
                elif self._check_os_version(EPOXY, version) and isinstance(
                    device, metadata_obj.ShareMetadata
                ):
                    device_metadata['type'] = 'share'
                    device_metadata['share_id'] = device.share_id
                    device_metadata['tag'] = device.tag
                else:
                    LOG.debug('Metadata for device of unknown type %s has not '
                              'been included in the '
                              'output', device.__class__.__name__)
                    continue

                device_metadata['bus'] = bus
                device_metadata['address'] = address
                if 'tags' in device:
                    device_metadata['tags'] = device.tags

                device_metadata_list.append(device_metadata)
        return device_metadata_list

    def _get_instance_dedicated_cpus(self):
        dedicated_cpus = []
        if self.instance.numa_topology:
            dedicated_cpus = sorted(list(itertools.chain.from_iterable([
                cell.pcpuset for cell in self.instance.numa_topology.cells
            ])))

        return dedicated_cpus

    def _handle_content(self, path_tokens):
        if len(path_tokens) == 1:
            raise KeyError("no listing for %s" % "/".join(path_tokens))
        if len(path_tokens) != 2:
            raise KeyError("Too many tokens for /%s" % CONTENT_DIR)
        return self.content[path_tokens[1]]

    def _handle_version(self, version, path):
        # request for /version, give a list of what is available
        ret = [MD_JSON_NAME]
        if self.userdata_raw is not None:
            ret.append(UD_NAME)
        if self._check_os_version(GRIZZLY, version):
            ret.append(PASS_NAME)
        if self._check_os_version(HAVANA, version):
            ret.append(VD_JSON_NAME)
        if self._check_os_version(LIBERTY, version):
            ret.append(NW_JSON_NAME)
        if self._check_os_version(NEWTON_TWO, version):
            ret.append(VD2_JSON_NAME)

        return ret

    def _user_data(self, version, path):
        if self.userdata_raw is None:
            raise KeyError(path)
        return self.userdata_raw

    def _network_data(self, version, path):
        if self.network_metadata is None:
            return jsonutils.dump_as_bytes({})
        return jsonutils.dump_as_bytes(self.network_metadata)

    def _password(self, version, path):
        if self._check_os_version(GRIZZLY, version):
            return password.handle_password
        raise KeyError(path)

    def _vendor_data(self, version, path):
        if self._check_os_version(HAVANA, version):
            self.set_mimetype(MIME_TYPE_APPLICATION_JSON)

            if (CONF.api.vendordata_providers and
                'StaticJSON' in CONF.api.vendordata_providers):
                return jsonutils.dump_as_bytes(
                    self.vendordata_providers['StaticJSON'].get())

        raise KeyError(path)

    def _vendor_data2(self, version, path):
        if self._check_os_version(NEWTON_TWO, version):
            self.set_mimetype(MIME_TYPE_APPLICATION_JSON)

            j = {}
            for provider in CONF.api.vendordata_providers:
                if provider == 'StaticJSON':
                    j['static'] = self.vendordata_providers['StaticJSON'].get()
                else:
                    values = self.vendordata_providers[provider].get()
                    for key in list(values):
                        if key in j:
                            LOG.warning('Removing duplicate metadata key: %s',
                                        key, instance=self.instance)
                            del values[key]
                    j.update(values)

            return jsonutils.dump_as_bytes(j)

        raise KeyError(path)

    def _check_version(self, required, requested, versions=VERSIONS):
        return versions.index(requested) >= versions.index(required)

    def _check_os_version(self, required, requested):
        return self._check_version(required, requested, OPENSTACK_VERSIONS)

    def _get_hostname(self):
        # TODO(stephenfin): At some point in the future, we may wish to
        # retrieve this information from neutron.
        if CONF.api.dhcp_domain:
            return '.'.join([self.instance.hostname, CONF.api.dhcp_domain])

        return self.instance.hostname

    def lookup(self, path):
        if path == "" or path[0] != "/":
            path = posixpath.normpath("/" + path)
        else:
            path = posixpath.normpath(path)

        # Set default mimeType. It will be modified only if there is a change
        self.set_mimetype(MIME_TYPE_TEXT_PLAIN)

        # fix up requests, prepending /ec2 to anything that does not match
        path_tokens = path.split('/')[1:]
        if path_tokens[0] not in ("ec2", "openstack"):
            if path_tokens[0] == "":
                # request for /
                path_tokens = ["ec2"]
            else:
                path_tokens = ["ec2"] + path_tokens
            path = "/" + "/".join(path_tokens)

        # all values of 'path' input starts with '/' and have no trailing /

        # specifically handle the top level request
        if len(path_tokens) == 1:
            if path_tokens[0] == "openstack":
                # NOTE(vish): don't show versions that are in the future
                today = timeutils.utcnow().strftime("%Y-%m-%d")
                versions = [v for v in OPENSTACK_VERSIONS if v <= today]
                if OPENSTACK_VERSIONS != versions:
                    LOG.debug("future versions %s hidden in version list",
                              [v for v in OPENSTACK_VERSIONS
                               if v not in versions], instance=self.instance)
                versions += ["latest"]
            else:
                versions = VERSIONS + ["latest"]
            return versions

        try:
            if path_tokens[0] == "openstack":
                data = self.get_openstack_item(path_tokens[1:])
            else:
                data = self.get_ec2_item(path_tokens[1:])
        except (InvalidMetadataVersion, KeyError):
            raise InvalidMetadataPath(path)

        return data

    def metadata_for_config_drive(self):
        """Yields (path, value) tuples for metadata elements."""
        # EC2 style metadata
        for version in VERSIONS + ["latest"]:
            if version in CONF.api.config_drive_skip_versions.split(' '):
                continue

            data = self.get_ec2_metadata(version)
            if 'user-data' in data:
                filepath = os.path.join('ec2', version, 'user-data')
                yield (filepath, data['user-data'])
                del data['user-data']

            try:
                del data['public-keys']['0']['_name']
            except KeyError:
                pass

            filepath = os.path.join('ec2', version, 'meta-data.json')
            yield (filepath, jsonutils.dump_as_bytes(data['meta-data']))

        ALL_OPENSTACK_VERSIONS = OPENSTACK_VERSIONS + ["latest"]
        for version in ALL_OPENSTACK_VERSIONS:
            path = 'openstack/%s/%s' % (version, MD_JSON_NAME)
            yield (path, self.lookup(path))

            path = 'openstack/%s/%s' % (version, UD_NAME)
            if self.userdata_raw is not None:
                yield (path, self.lookup(path))

            if self._check_version(HAVANA, version, ALL_OPENSTACK_VERSIONS):
                path = 'openstack/%s/%s' % (version, VD_JSON_NAME)
                yield (path, self.lookup(path))

            if self._check_version(LIBERTY, version, ALL_OPENSTACK_VERSIONS):
                path = 'openstack/%s/%s' % (version, NW_JSON_NAME)
                yield (path, self.lookup(path))

            if self._check_version(NEWTON_TWO, version,
                                   ALL_OPENSTACK_VERSIONS):
                path = 'openstack/%s/%s' % (version, VD2_JSON_NAME)
                yield (path, self.lookup(path))

        for (cid, content) in self.content.items():
            yield ('%s/%s/%s' % ("openstack", CONTENT_DIR, cid), content)


class RouteConfiguration(object):
    """Routes metadata paths to request handlers."""

    def __init__(self, path_handler):
        self.path_handlers = path_handler

    def _version(self, version):
        if version == "latest":
            version = OPENSTACK_VERSIONS[-1]

        if version not in OPENSTACK_VERSIONS:
            raise InvalidMetadataVersion(version)

        return version

    def handle_path(self, path_tokens):
        version = self._version(path_tokens[0])
        if len(path_tokens) == 1:
            path = VERSION
        else:
            path = '/'.join(path_tokens[1:])

        path_handler = self.path_handlers[path]

        if path_handler is None:
            raise KeyError(path)

        return path_handler(version, path)


def get_metadata_by_address(address):
    ctxt = context.get_admin_context()
    fixed_ip = neutron.API().get_fixed_ip_by_address(ctxt, address)
    LOG.info('Fixed IP %(ip)s translates to instance UUID %(uuid)s',
             {'ip': address, 'uuid': fixed_ip['instance_uuid']})

    return get_metadata_by_instance_id(fixed_ip['instance_uuid'],
                                       address,
                                       ctxt)


def get_metadata_by_instance_id(instance_id, address, ctxt=None):
    ctxt = ctxt or context.get_admin_context()
    attrs = ['ec2_ids', 'flavor', 'info_cache',
             'metadata', 'system_metadata',
             'security_groups', 'keypairs',
             'device_metadata', 'numa_topology']

    if CONF.api.local_metadata_per_cell:
        instance = objects.Instance.get_by_uuid(ctxt, instance_id,
                                                expected_attrs=attrs)
        return InstanceMetadata(instance, address)

    try:
        im = objects.InstanceMapping.get_by_instance_uuid(ctxt, instance_id)
    except exception.InstanceMappingNotFound:
        LOG.warning('Instance mapping for %(uuid)s not found; '
                    'cell setup is incomplete', {'uuid': instance_id})
        instance = objects.Instance.get_by_uuid(ctxt, instance_id,
                                                expected_attrs=attrs)
        return InstanceMetadata(instance, address)

    with context.target_cell(ctxt, im.cell_mapping) as cctxt:
        instance = objects.Instance.get_by_uuid(cctxt, instance_id,
                                                expected_attrs=attrs)
        return InstanceMetadata(instance, address)


def _format_instance_mapping(instance):
    bdms = instance.get_bdms()
    return block_device.instance_block_mapping(instance, bdms)


def ec2_md_print(data):
    if isinstance(data, dict):
        output = ''
        for key in sorted(data.keys()):
            if key == '_name':
                continue
            if isinstance(data[key], dict):
                if '_name' in data[key]:
                    output += str(data[key]['_name'])
                else:
                    output += key + '/'
            else:
                output += key

            output += '\n'
        return output[:-1]
    elif isinstance(data, list):
        return '\n'.join(data)
    elif isinstance(data, (bytes, str)):
        return data
    else:
        return str(data)


def find_path_in_tree(data, path_tokens):
    # given a dict/list tree, and a path in that tree, return data found there.
    for i in range(0, len(path_tokens)):
        if isinstance(data, dict) or isinstance(data, list):
            if path_tokens[i] in data:
                data = data[path_tokens[i]]
            else:
                raise KeyError("/".join(path_tokens[0:i]))
        else:
            if i != len(path_tokens) - 1:
                raise KeyError("/".join(path_tokens[0:i]))
            data = data[path_tokens[i]]
    return data
