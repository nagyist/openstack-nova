{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "OS-EXT-AZ:availability_zone": "us-west",
        "OS-EXT-SRV-ATTR:hostname": "%(hostname)s",
        "OS-EXT-STS:power_state": 1,
        "OS-EXT-STS:task_state": null,
        "OS-EXT-STS:vm_state": "active",
        "OS-SRV-USG:launched_at": "%(strtime)s",
        "OS-SRV-USG:terminated_at": null,
        "accessIPv4": "1.2.3.4",
        "accessIPv6": "80fe::",
        "addresses": {
            "private": [
                {
                    "OS-EXT-IPS-MAC:mac_addr": "00:0c:29:0d:11:74",
                    "OS-EXT-IPS:type": "fixed",
                    "addr": "192.168.1.30",
                    "version": 4
                }
            ]
        },
        "adminPass": "seekr3t",
        "config_drive": "",
        "created": "%(isotime)s",
        "description": null,
        "flavor": {
            "disk": 1,
            "ephemeral": 0,
            "extra_specs": {},
            "original_name": "m1.tiny",
            "ram": 512,
            "swap": 0,
            "vcpus": 1
        },
        "hostId": "2091634baaccdc4c5a1d57069c833e402921df696b7f970791b12ec6",
        "id": "%(id)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(compute_endpoint)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "key_name": null,
        "links": [
            {
                "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(compute_endpoint)s/servers/%(id)s",
                "rel": "bookmark"
            }
        ],
        "locked": false,
        "locked_reason": null,
        "metadata": {
            "meta_var": "meta_val"
        },
        "name": "foobar",
        "os-extended-volumes:volumes_attached": [],
        "pinned_availability_zone": "us-west",
        "progress": 0,
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
        "user_data": "ZWNobyAiaGVsbG8gd29ybGQi",
        "user_id": "fake"
    }
}
