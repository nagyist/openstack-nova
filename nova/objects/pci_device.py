# Copyright 2013 Intel Corporation
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

import copy

from oslo_db import api as oslo_db_api
from oslo_db.sqlalchemy import update_match
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from oslo_utils import versionutils

from nova.db.main import api as db
from nova.db.main import models as db_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


def compare_pci_device_attributes(obj_a, obj_b):
    if not isinstance(obj_b, PciDevice):
        return False
    pci_ignore_fields = base.NovaPersistentObject.fields.keys()
    for name in obj_a.obj_fields:
        if name in pci_ignore_fields:
            continue
        is_set_a = obj_a.obj_attr_is_set(name)
        is_set_b = obj_b.obj_attr_is_set(name)
        if is_set_a != is_set_b:
            return False
        if is_set_a:
            if getattr(obj_a, name) != getattr(obj_b, name):
                return False
    return True


@base.NovaObjectRegistry.register
class PciDevice(base.NovaPersistentObject, base.NovaObject):

    """Object to represent a PCI device on a compute node.

    PCI devices are managed by the compute resource tracker, which discovers
    the devices from the hardware platform, claims, allocates and frees
    devices for instances.

    The PCI device information is permanently maintained in a database.
    This makes it convenient to get PCI device information, like physical
    function for a VF device, adjacent switch IP address for a NIC,
    hypervisor identification for a PCI device, etc. It also provides a
    convenient way to check device allocation information for administrator
    purposes.

    A device can be in available/claimed/allocated/deleted/removed state.

    A device is available when it is discovered..

    A device is claimed prior to being allocated to an instance. Normally the
    transition from claimed to allocated is quick. However, during a resize
    operation the transition can take longer, because devices are claimed in
    prep_resize and allocated in finish_resize.

    A device becomes removed when hot removed from a node (i.e. not found in
    the next auto-discover) but not yet synced with the DB. A removed device
    should not be allocated to any instance, and once deleted from the DB,
    the device object is changed to deleted state and no longer synced with
    the DB.

    Filed notes::

        | 'dev_id':
        |   Hypervisor's identification for the device, the string format
        |   is hypervisor specific
        | 'extra_info':
        |   Device-specific properties like PF address, switch ip address etc.

    """

    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: added request_id field
    # Version 1.3: Added field to represent PCI device NUMA node
    # Version 1.4: Added parent_addr field
    # Version 1.5: Added 2 new device statuses: UNCLAIMABLE and UNAVAILABLE
    # Version 1.6: Added uuid field
    # Version 1.7: Added 'vdpa' to 'dev_type' field
    VERSION = '1.7'

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
        # Note(yjiang5): the compute_node_id may be None because the pci
        # device objects are created before the compute node is created in DB
        'compute_node_id': fields.IntegerField(nullable=True),
        'address': fields.StringField(),
        'vendor_id': fields.StringField(),
        'product_id': fields.StringField(),
        'dev_type': fields.PciDeviceTypeField(),
        'status': fields.PciDeviceStatusField(),
        'dev_id': fields.StringField(nullable=True),
        'label': fields.StringField(nullable=True),
        'instance_uuid': fields.StringField(nullable=True),
        'request_id': fields.StringField(nullable=True),
        'extra_info': fields.DictOfStringsField(default={}),
        'numa_node': fields.IntegerField(nullable=True),
        'parent_addr': fields.StringField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'request_id' in primitive:
            del primitive['request_id']
        if target_version < (1, 4) and 'parent_addr' in primitive:
            if primitive['parent_addr'] is not None:
                extra_info = primitive.get('extra_info', {})
                extra_info['phys_function'] = primitive['parent_addr']
            del primitive['parent_addr']
        if target_version < (1, 5) and 'parent_addr' in primitive:
            added_statuses = (fields.PciDeviceStatus.UNCLAIMABLE,
                              fields.PciDeviceStatus.UNAVAILABLE)
            base.raise_on_too_new_values(
                target_version, primitive, 'status', added_statuses)
        if target_version < (1, 6) and 'uuid' in primitive:
            del primitive['uuid']
        if target_version < (1, 7) and 'dev_type' in primitive:
            base.raise_on_too_new_values(
                target_version, primitive,
                'dev_type', (fields.PciDeviceType.VDPA,))

    def __repr__(self):
        return (
            f'PciDevice(address={self.address}, '
            f'compute_node_id={self.compute_node_id})'
        )

    def update_device(self, dev_dict):
        """Sync the content from device dictionary to device object.

        The resource tracker updates the available devices periodically.
        To avoid meaningless syncs with the database, we update the device
        object only if a value changed.
        """

        # Note(yjiang5): status/instance_uuid should only be updated by
        # functions like claim/allocate etc. The id is allocated by
        # database. The extra_info is created by the object.
        no_changes = ('status', 'instance_uuid', 'id', 'extra_info')
        for key in no_changes:
            dev_dict.pop(key, None)

        # NOTE(ndipanov): This needs to be set as it's accessed when matching
        dev_dict.setdefault('parent_addr')

        for k, v in dev_dict.items():
            if k in self.fields.keys():
                setattr(self, k, v)
            else:
                # NOTE(yjiang5): extra_info.update does not update
                # obj_what_changed, set it explicitly
                # NOTE(ralonsoh): list of parameters currently added to
                # "extra_info" dict:
                #     - "capabilities": dict of (strings/list of strings)
                #     - "parent_ifname": the netdev name of the parent (PF)
                #        device of a VF
                #     - "mac_address": the MAC address of the PF
                #     - "managed": "true"/"false" if the device is managed by
                #       hypervisor
                #     - "live_migratable": true/false if the device can be live
                #       migratable
                extra_info = self.extra_info
                data = v if isinstance(v, str) else jsonutils.dumps(v)
                extra_info.update({k: data})
                self.extra_info = extra_info

        # Remove the tag keys if they were set previously.
        # As in the above case, we must explicitly assign to self.extra_info
        # so that obj_what_changed detects the modification and triggers
        # a save later.
        tags_to_clean = ["managed", "live_migratable"]
        for tag in tags_to_clean:
            if tag not in dev_dict and tag in self.extra_info:
                extra_info = self.extra_info
                del extra_info[tag]
                self.extra_info = extra_info

    def __init__(self, *args, **kwargs):
        super(PciDevice, self).__init__(*args, **kwargs)

        # NOTE(ndipanov): These are required to build an in-memory device tree
        # but don't need to be proper fields (and can't easily be as they would
        # hold circular references)
        self.parent_device = None
        self.child_devices = []

    @base.lazy_load_counter
    def obj_load_attr(self, attr):
        if attr in ['extra_info']:
            # NOTE(danms): extra_info used to be defaulted during init,
            # so make sure any bare instantiations of this object can
            # rely on the expectation that referencing that field will
            # not fail.
            self.obj_set_defaults(attr)
        else:
            super(PciDevice, self).obj_load_attr(attr)

    def __eq__(self, other):
        return compare_pci_device_attributes(self, other)

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def populate_dev_uuids(cls, context, max_count):
        @db.pick_context_manager_reader
        def get_devs_no_uuid(context):
            return context.session.query(db_models.PciDevice).\
                    filter_by(uuid=None).limit(max_count).all()

        db_devs = get_devs_no_uuid(context)

        done = 0
        for db_dev in db_devs:
            cls._create_uuid(context, db_dev['id'])
            done += 1

        return done, done

    @classmethod
    def _from_db_object(cls, context, pci_device, db_dev):
        for key in pci_device.fields:
            if key == 'uuid' and db_dev['uuid'] is None:
                # NOTE(danms): While the records could be nullable,
                # generate a UUID on read since the object requires it
                dev_id = db_dev['id']
                db_dev[key] = cls._create_uuid(context, dev_id)

            if key == 'extra_info':
                extra_info = db_dev.get('extra_info')
                pci_device.extra_info = jsonutils.loads(extra_info)
                continue

            setattr(pci_device, key, db_dev[key])

        pci_device._context = context
        pci_device.obj_reset_changes()
        return pci_device

    @staticmethod
    @oslo_db_api.wrap_db_retry(max_retries=1, retry_on_deadlock=True)
    def _create_uuid(context, dev_id):
        # NOTE(mdbooth): This method is only required until uuid is made
        # non-nullable in a future release.

        # NOTE(mdbooth): We wrap this method in a retry loop because it can
        # fail (safely) on multi-master galera if concurrent updates happen on
        # different masters. It will never fail on single-master. We can only
        # ever need one retry.

        uuid = uuidutils.generate_uuid()
        values = {'uuid': uuid}
        compare = db_models.PciDevice(id=dev_id, uuid=None)

        # NOTE(mdbooth): We explicitly use an independent transaction context
        # here so as not to fail if:
        # 1. We retry.
        # 2. We're in a read transaction. This is an edge case of what's
        #    normally a read operation. Forcing everything (transitively) which
        #    reads a PCI device to be in a write transaction for a narrow
        #    temporary edge case is undesirable.
        tctxt = db.get_context_manager(context).writer.independent
        with tctxt.using(context):
            query = context.session.query(db_models.PciDevice).\
                        filter_by(id=dev_id)

            try:
                query.update_on_match(compare, 'id', values)
            except update_match.NoRowsMatched:
                # We can only get here if we raced, and another writer already
                # gave this PCI device a UUID
                result = query.one()
                uuid = result['uuid']

        return uuid

    @base.remotable_classmethod
    def get_by_dev_addr(cls, context, compute_node_id, dev_addr):
        db_dev = db.pci_device_get_by_addr(
            context, compute_node_id, dev_addr)
        return cls._from_db_object(context, cls(), db_dev)

    @base.remotable_classmethod
    def get_by_dev_id(cls, context, id):
        db_dev = db.pci_device_get_by_id(context, id)
        return cls._from_db_object(context, cls(), db_dev)

    @classmethod
    def create(cls, context, dev_dict):
        """Create a PCI device based on hypervisor information.

        As the device object is just created and is not synced with db yet
        thus we should not reset changes here for fields from dict.
        """
        pci_device = cls()
        # NOTE(danms): extra_info used to always be defaulted during init,
        # so make sure we replicate that behavior outside of init here
        # for compatibility reasons.
        pci_device.obj_set_defaults('extra_info')
        pci_device.update_device(dev_dict)
        pci_device.status = fields.PciDeviceStatus.AVAILABLE
        pci_device.uuid = uuidutils.generate_uuid()
        pci_device._context = context
        return pci_device

    @base.remotable
    def save(self):
        if self.status == fields.PciDeviceStatus.REMOVED:
            self.status = fields.PciDeviceStatus.DELETED
            db.pci_device_destroy(self._context, self.compute_node_id,
                                  self.address)
        elif self.status != fields.PciDeviceStatus.DELETED:
            # TODO(jaypipes): Remove in 2.0 version of object. This does an
            # inline migration to populate the uuid field. A similar migration
            # is done in the _from_db_object() method to migrate objects as
            # they are read from the DB.
            if 'uuid' not in self:
                self.uuid = uuidutils.generate_uuid()
            updates = self.obj_get_changes()

            if 'extra_info' in updates:
                updates['extra_info'] = jsonutils.dumps(updates['extra_info'])
            if updates:
                db_pci = db.pci_device_update(self._context,
                                              self.compute_node_id,
                                              self.address, updates)
                self._from_db_object(self._context, self, db_pci)

    @staticmethod
    def _bulk_update_status(dev_list, status):
        for dev in dev_list:
            dev.status = status

    def claim(self, instance_uuid):
        if self.status != fields.PciDeviceStatus.AVAILABLE:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=[fields.PciDeviceStatus.AVAILABLE])

        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            # Update PF status to CLAIMED if all of it dependants are free
            # and set their status to UNCLAIMABLE
            vfs_list = self.child_devices
            non_free_dependants = [
                vf for vf in vfs_list if not vf.is_available()]
            if non_free_dependants:
                # NOTE(gibi): There should not be any dependent devices that
                # are UNCLAIMABLE or UNAVAILABLE as the parent is AVAILABLE,
                # but we got reports in bug 1969496 that this inconsistency
                # can happen. So check if the only non-free devices are in
                # state UNCLAIMABLE or UNAVAILABLE then we log a warning but
                # allow to claim the parent.
                actual_statuses = {
                    child.status for child in non_free_dependants}
                allowed_non_free_statues = {
                    fields.PciDeviceStatus.UNCLAIMABLE,
                    fields.PciDeviceStatus.UNAVAILABLE,
                }
                if actual_statuses - allowed_non_free_statues == set():
                    LOG.warning(
                        "Some child device of parent %s is in an inconsistent "
                        "state. If you can reproduce this warning then please "
                        "report a bug at "
                        "https://bugs.launchpad.net/nova/+filebug with "
                        "reproduction steps. Inconsistent children with "
                        "state: %s",
                        self.address,
                        ",".join(
                            "%s - %s" % (child.address, child.status)
                            for child in non_free_dependants
                        ),
                    )

                else:
                    raise exception.PciDeviceVFInvalidStatus(
                        compute_node_id=self.compute_node_id,
                        address=self.address)
            self._bulk_update_status(vfs_list,
                                           fields.PciDeviceStatus.UNCLAIMABLE)

        elif self.dev_type in (
            fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA
        ):
            # Update VF status to CLAIMED if it's parent has not been
            # previously allocated or claimed
            # When claiming/allocating a VF, it's parent PF becomes
            # unclaimable/unavailable. Therefore, it is expected to find the
            # parent PF in an unclaimable/unavailable state for any following
            # claims to a sibling VF

            parent_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                                  fields.PciDeviceStatus.UNCLAIMABLE,
                                  fields.PciDeviceStatus.UNAVAILABLE)
            parent = self.parent_device
            if parent:
                if parent.status not in parent_ok_statuses:
                    raise exception.PciDevicePFInvalidStatus(
                        compute_node_id=self.compute_node_id,
                        address=self.parent_addr, status=self.status,
                        vf_address=self.address,
                        hopestatus=parent_ok_statuses)
                # Set PF status
                if parent.status == fields.PciDeviceStatus.AVAILABLE:
                    parent.status = fields.PciDeviceStatus.UNCLAIMABLE
            else:
                LOG.debug('Physical function addr: %(pf_addr)s parent of '
                          'VF addr: %(vf_addr)s was not found',
                          {'pf_addr': self.parent_addr,
                           'vf_addr': self.address})

        self.status = fields.PciDeviceStatus.CLAIMED
        self.instance_uuid = instance_uuid

    def allocate(self, instance):
        ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                       fields.PciDeviceStatus.CLAIMED)
        parent_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                              fields.PciDeviceStatus.UNCLAIMABLE,
                              fields.PciDeviceStatus.UNAVAILABLE)
        dependants_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                                  fields.PciDeviceStatus.UNCLAIMABLE)
        if self.status not in ok_statuses:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=ok_statuses)
        if (self.status == fields.PciDeviceStatus.CLAIMED and
                self.instance_uuid != instance['uuid']):
            raise exception.PciDeviceInvalidOwner(
                compute_node_id=self.compute_node_id,
                address=self.address, owner=self.instance_uuid,
                hopeowner=instance['uuid'])
        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            vfs_list = self.child_devices
            if not all([vf.status in dependants_ok_statuses for
                        vf in vfs_list]):
                raise exception.PciDeviceVFInvalidStatus(
                    compute_node_id=self.compute_node_id,
                    address=self.address)
            self._bulk_update_status(vfs_list,
                                     fields.PciDeviceStatus.UNAVAILABLE)

        elif self.dev_type in (
            fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA
        ):
            parent = self.parent_device
            if parent:
                if parent.status not in parent_ok_statuses:
                    raise exception.PciDevicePFInvalidStatus(
                        compute_node_id=self.compute_node_id,
                        address=self.parent_addr, status=self.status,
                        vf_address=self.address,
                        hopestatus=parent_ok_statuses)
                # Set PF status
                parent.status = fields.PciDeviceStatus.UNAVAILABLE
            else:
                LOG.debug('Physical function addr: %(pf_addr)s parent of '
                          'VF addr: %(vf_addr)s was not found',
                           {'pf_addr': self.parent_addr,
                            'vf_addr': self.address})

        self.status = fields.PciDeviceStatus.ALLOCATED
        self.instance_uuid = instance['uuid']

        # Notes(yjiang5): remove this check when instance object for
        # compute manager is finished
        if isinstance(instance, dict):
            if 'pci_devices' not in instance:
                instance['pci_devices'] = []
            instance['pci_devices'].append(copy.copy(self))
        else:
            instance.pci_devices.objects.append(copy.copy(self))

    def remove(self):
        # We allow removal of a device is if it is unused. It can be unused
        # either by being in available state or being in a state that shows
        # that the parent or child device blocks the consumption of this device
        expected_states = [
            fields.PciDeviceStatus.AVAILABLE,
            fields.PciDeviceStatus.UNAVAILABLE,
            fields.PciDeviceStatus.UNCLAIMABLE,
        ]
        if self.status not in expected_states:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=expected_states)
        # Just to be on the safe side, do not allow removal of device that has
        # an owner even if the state of the device suggests that it is not
        # owned.
        if 'instance_uuid' in self and self.instance_uuid is not None:
            raise exception.PciDeviceInvalidOwner(
                compute_node_id=self.compute_node_id,
                address=self.address,
                owner=self.instance_uuid,
                hopeowner=None,
            )

        self.status = fields.PciDeviceStatus.REMOVED
        self.instance_uuid = None
        self.request_id = None

    def free(self, instance=None):
        ok_statuses = (fields.PciDeviceStatus.ALLOCATED,
                       fields.PciDeviceStatus.CLAIMED)
        free_devs = []
        if self.status not in ok_statuses:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=ok_statuses)
        if instance and self.instance_uuid != instance['uuid']:
            raise exception.PciDeviceInvalidOwner(
                compute_node_id=self.compute_node_id,
                address=self.address, owner=self.instance_uuid,
                hopeowner=instance['uuid'])
        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            # Set all PF dependants status to AVAILABLE
            vfs_list = self.child_devices
            self._bulk_update_status(vfs_list,
                                     fields.PciDeviceStatus.AVAILABLE)
            free_devs.extend(vfs_list)
        if self.dev_type in (
            fields.PciDeviceType.SRIOV_VF, fields.PciDeviceType.VDPA
        ):
            # Set PF status to AVAILABLE if all of it's VFs are free
            parent = self.parent_device
            if not parent:
                LOG.debug('Physical function addr: %(pf_addr)s parent of '
                          'VF addr: %(vf_addr)s was not found',
                           {'pf_addr': self.parent_addr,
                            'vf_addr': self.address})
            else:
                vfs_list = parent.child_devices
                if all([vf.is_available() for vf in vfs_list
                        if vf.id != self.id]):
                    parent.status = fields.PciDeviceStatus.AVAILABLE
                    free_devs.append(parent)
        old_status = self.status
        self.status = fields.PciDeviceStatus.AVAILABLE
        free_devs.append(self)
        self.instance_uuid = None
        self.request_id = None
        if old_status == fields.PciDeviceStatus.ALLOCATED and instance:
            # Notes(yjiang5): remove this check when instance object for
            # compute manager is finished
            existed = next((dev for dev in instance['pci_devices']
                if dev.id == self.id))
            if isinstance(instance, dict):
                instance['pci_devices'].remove(existed)
            else:
                instance.pci_devices.objects.remove(existed)
        return free_devs

    def is_available(self):
        return self.status == fields.PciDeviceStatus.AVAILABLE

    @property
    def card_serial_number(self):
        caps_json = self.extra_info.get('capabilities', "{}")
        caps = jsonutils.loads(caps_json)
        return caps.get('vpd', {}).get('card_serial_number')

    @property
    def sriov_cap(self):
        caps_json = self.extra_info.get('capabilities', '{}')
        caps = jsonutils.loads(caps_json)
        return caps.get('sriov', {})

    @property
    def mac_address(self):
        """The MAC address of the PF physical device or None if the device is
        not a PF or if the MAC is not available.
        """
        return self.extra_info.get('mac_address')

    @property
    def network_caps(self):
        """PCI device network capabilities or empty list if not available"""
        caps_json = self.extra_info.get('capabilities', '{}')
        caps = jsonutils.loads(caps_json)
        return caps.get('network', [])


@base.NovaObjectRegistry.register
class PciDeviceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              PciDevice <= 1.1
    # Version 1.1: PciDevice 1.2
    # Version 1.2: PciDevice 1.3
    # Version 1.3: Adds get_by_parent_address
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('PciDevice'),
        }

    def __init__(self, *args, **kwargs):
        super(PciDeviceList, self).__init__(*args, **kwargs)
        if 'objects' not in kwargs:
            self.objects = []
            self.obj_reset_changes()

    @base.remotable_classmethod
    def get_by_compute_node(cls, context, node_id):
        db_dev_list = db.pci_device_get_all_by_node(context, node_id)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, uuid):
        db_dev_list = db.pci_device_get_all_by_instance_uuid(context, uuid)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)

    @base.remotable_classmethod
    def get_by_parent_address(cls, context, node_id, parent_addr):
        db_dev_list = db.pci_device_get_all_by_parent_addr(context,
                                                           node_id,
                                                           parent_addr)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)

    def __repr__(self):
        return f"PciDeviceList(objects={[repr(obj) for obj in self.objects]})"
