..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Command-line Utilities
======================

In this section you will find information on Nova's command line utilities.

Nova Management Commands
------------------------

These commands are used to manage existing installations. They are designed to
be run by operators in an environment where they have direct access to the nova
database.

.. toctree::
   :maxdepth: 1

   nova-manage
   nova-policy
   nova-status

Service Daemons
---------------

The service daemons make up a functioning nova environment. All of these are
expected to be started by an init system, expect to read a nova.conf file, and
daemonize correctly after starting up.

.. toctree::
   :maxdepth: 1

   nova-compute
   nova-conductor
   nova-novncproxy
   nova-scheduler
   nova-serialproxy
   nova-spicehtml5proxy

WSGI Services
-------------

Starting in the 2025.2 release, the only way to deploy the nova api is in a
wsgi container (uwsgi or apache/mod_wsgi). These are the wsgi entry points to
do that:

* :doc:`nova-api-wsgi </user/wsgi>`
* :doc:`nova-metadata-wsgi </user/wsgi>`

Additional Tools
----------------

There are a few additional cli tools which nova services call when
appropriate. This should not need to be called directly by operators, but they
are documented for completeness and debugging if something goes wrong.

.. toctree::
   :maxdepth: 1

   nova-rootwrap
