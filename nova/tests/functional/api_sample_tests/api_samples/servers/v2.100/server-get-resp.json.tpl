
{
    "server": {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "OS-EXT-IPS-MAC:mac_addr": "00:0c:29:0d:11:74",
                    "OS-EXT-IPS:type": "fixed",
                    "version": 4
                }
            ]
        },
        "created": "%(isotime)s",
        "description": null,
        "locked": false,
        "locked_reason": null,
        "flavor": {
            "disk": 1,
            "ephemeral": 0,
            "extra_specs": {},
            "original_name": "m1.tiny",
            "ram": 512,
            "swap": 0,
            "vcpus": 1
        },
        "hostId": "%(hostid)s",
        "id": "%(id)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(compute_endpoint)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ],
            "properties": {
                "architecture": "x86_64",
                "auto_disk_config": "True",
                "base_image_ref": "%(uuid)s",
                "container_format": "ova",
                "disk_format": "vhd",
                "kernel_id": "nokernel",
                "min_disk": "1",
                "min_ram": "0",
                "ramdisk_id": "nokernel"
            }
        },
        "key_name": null,
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "My Server Name": "Apache1"
        },
        "name": "new-server-test",
        "config_drive": "%(cdrive)s",
        "OS-DCF:diskConfig": "AUTO",
        "OS-EXT-AZ:availability_zone": "us-west",
        "OS-EXT-SRV-ATTR:hostname": "%(hostname)s",
        "OS-EXT-STS:power_state": 1,
        "OS-EXT-STS:task_state": null,
        "OS-EXT-STS:vm_state": "active",
        "os-extended-volumes:volumes_attached": [
            {"id": "volume_id1", "delete_on_termination": false},
            {"id": "volume_id2", "delete_on_termination": false}
        ],
        "OS-SRV-USG:launched_at": "%(strtime)s",
        "OS-SRV-USG:terminated_at": null,
        "pinned_availability_zone": "us-west",
        "progress": 0,
        "scheduler_hints": {
            "same_host": [
                "48e6a9f6-30af-47e0-bc04-acaed113bb4e"
            ]
        },
        "security_groups": [
            {
                "name": "default"
            }
        ],
        "server_groups": [],
        "status": "ACTIVE",
        "tags": [],
        "tenant_id": "6f70656e737461636b20342065766572",
        "trusted_image_certificates": null,
        "updated": "%(isotime)s",
        "user_id": "fake"
    }
}
